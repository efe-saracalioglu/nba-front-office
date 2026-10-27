from __future__ import annotations

import logging
import time
from datetime import date

import httpx
import pandas as pd
from bs4 import BeautifulSoup, Comment
from tenacity import retry, stop_after_attempt, wait_exponential

from data.config import RAW_DIR, season_end_year

log = logging.getLogger(__name__)

BASE_URL = "https://www.basketball-reference.com"
CACHE_DIR = RAW_DIR / "bbref"
REQUEST_PAUSE_S = 4.0
HEADERS = {"User-Agent": "front-office-etl/0.1 (portfolio research project)"}

_last_request = 0.0


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=5, min=5, max=60), reraise=True)
def _get(url: str) -> str:
    global _last_request
    wait = REQUEST_PAUSE_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()
    resp = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def fetch_html(path: str, cache_name: str, refresh: bool = False) -> str:
    cache = CACHE_DIR / cache_name
    if cache.exists() and not refresh:
        return cache.read_text(encoding="utf-8")
    log.info("bbref fetch %s", path)
    html = _get(BASE_URL + path)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(html, encoding="utf-8")
    return html


def _find_table(html: str, table_id: str):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id=table_id)
    if table is None:
        for c in soup.find_all(string=lambda s: isinstance(s, Comment) and table_id in s):
            table = BeautifulSoup(c, "lxml").find("table", id=table_id)
            if table is not None:
                break
    if table is None:
        raise ValueError(f"table #{table_id} not found")
    return table


def parse_table(html: str, table_id: str) -> list[dict]:
    rows = []
    for tr in _find_table(html, table_id).tbody.find_all("tr"):
        if "thead" in (tr.get("class") or []):
            continue
        cells = {}
        for cell in tr.find_all(["th", "td"]):
            stat = cell.get("data-stat")
            if stat:
                cells[stat] = cell
        if cells:
            rows.append(cells)
    return rows


def _num(cell) -> float | None:
    if cell is None:
        return None
    raw = cell.get("csk") or cell.get_text(strip=True)
    raw = raw.replace("$", "").replace(",", "")
    try:
        return float(raw)
    except ValueError:
        return None


ADVANCED_STATS = {
    "age": "age",
    "games": "g",
    "games_started": "gs",
    "mp": "mp",
    "per": "per",
    "ts_pct": "ts_pct",
    "fg3a_per_fga_pct": "fg3a_rate",
    "fta_per_fga_pct": "fta_rate",
    "orb_pct": "orb_pct",
    "drb_pct": "drb_pct",
    "trb_pct": "trb_pct",
    "ast_pct": "ast_pct",
    "stl_pct": "stl_pct",
    "blk_pct": "blk_pct",
    "tov_pct": "tov_pct",
    "usg_pct": "usg_pct",
    "ows": "ows",
    "dws": "dws",
    "ws": "ws",
    "ws_per_48": "ws_per_48",
    "obpm": "obpm",
    "dbpm": "dbpm",
    "bpm": "bpm",
    "vorp": "vorp",
}
_PCT_SCALED = {
    "orb_pct",
    "drb_pct",
    "trb_pct",
    "ast_pct",
    "stl_pct",
    "blk_pct",
    "tov_pct",
    "usg_pct",
}


def parse_advanced(html: str, season: str) -> pd.DataFrame:
    out = []
    for r in parse_table(html, "advanced"):
        name_cell = r.get("name_display") or r.get("player")
        if name_cell is None or not name_cell.get("data-append-csv"):
            continue
        team_cell = r.get("team_name_abbr") or r.get("team_id")
        rec = {
            "bbref_id": name_cell["data-append-csv"],
            "player_name": name_cell.get_text(strip=True),
            "season": season,
            "team": team_cell.get_text(strip=True) if team_cell else None,
            "position": r["pos"].get_text(strip=True) if "pos" in r else None,
        }
        for stat, col in ADVANCED_STATS.items():
            cell = r.get(stat)
            value = _num(cell)
            if col in _PCT_SCALED and value is not None and not cell.get("csk"):
                value /= 100
            rec[col] = value
        out.append(rec)
    df = pd.DataFrame(out)
    df = df.drop_duplicates(subset=["bbref_id"], keep="first").drop(columns="team")
    for col in ("age", "g", "gs", "mp"):
        df[col] = df[col].astype("Int64")
    return df.reset_index(drop=True)


def fetch_advanced(season: str, refresh: bool = False) -> pd.DataFrame:
    year = season_end_year(season)
    html = fetch_html(f"/leagues/NBA_{year}_advanced.html", f"advanced_{year}.html", refresh)
    return parse_advanced(html, season)


def parse_contracts(html: str, snapshot: date) -> pd.DataFrame:
    table = _find_table(html, "player-contracts")
    year_cols = {
        th["data-stat"]: th.get_text(strip=True)
        for th in table.thead.find_all("th")
        if (th.get("data-stat") or "").startswith("y") and th["data-stat"][1:].isdigit()
    }
    out = []
    for r in parse_table(html, "player-contracts"):
        player = r.get("player")
        if player is None or not player.get("data-append-csv"):
            continue
        team = r["team_id"].get_text(strip=True) if "team_id" in r else None
        for stat, season in year_cols.items():
            salary = _num(r.get(stat))
            if salary is None:
                continue
            classes = r[stat].get("class") or []
            option = (
                "player" if "salary-pl" in classes else "team" if "salary-tm" in classes else "none"
            )
            out.append(
                {
                    "bbref_id": player["data-append-csv"],
                    "player_name": player.get_text(strip=True),
                    "bbref_team": team,
                    "season": season,
                    "salary": int(salary),
                    "option_type": option,
                    "snapshot_date": snapshot,
                }
            )
    df = pd.DataFrame(out)
    return (
        df.sort_values("salary", ascending=False)
        .drop_duplicates(subset=["bbref_id", "season"], keep="first")
        .reset_index(drop=True)
    )


def fetch_contracts(refresh: bool = False, snapshot: date | None = None) -> pd.DataFrame:
    html = fetch_html("/contracts/players.html", "contracts_players.html", refresh)
    cache = CACHE_DIR / "contracts_players.html"
    snapshot = snapshot or date.fromtimestamp(cache.stat().st_mtime)
    return parse_contracts(html, snapshot)
