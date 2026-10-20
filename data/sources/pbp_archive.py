from __future__ import annotations

import logging
import re
import tarfile

import httpx
import numpy as np
import pandas as pd
from tenacity import retry, stop_after_attempt, wait_exponential

from data.config import RAW_DIR, season_end_year

log = logging.getLogger(__name__)

ARCHIVE_URL = "https://github.com/shufinskiy/nba_data/raw/main/datasets/nbastatsv3_{year}.tar.xz"
CACHE_DIR = RAW_DIR / "pbp"
_CLOCK = re.compile(r"PT(\d+)M([\d.]+)S")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=2, max=30), reraise=True)
def _download(url: str) -> bytes:
    resp = httpx.get(url, timeout=120, follow_redirects=True)
    resp.raise_for_status()
    return resp.content


def archive_path(season: str, refresh: bool = False):
    start_year = season_end_year(season) - 1
    path = CACHE_DIR / f"nbastatsv3_{start_year}.tar.xz"
    if not path.exists() or refresh:
        log.info("pbp download %s", season)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_download(ARCHIVE_URL.format(year=start_year)))
    return path


def clock_to_seconds(clock: pd.Series) -> pd.Series:
    parts = clock.str.extract(_CLOCK)
    return parts[0].astype(float) * 60 + parts[1].astype(float)


def _secondary_type(desc: pd.Series) -> pd.Series:
    out = pd.Series("Other", index=desc.index)
    out[desc.str.contains("STEAL", na=False)] = "Steal"
    out[desc.str.contains("BLOCK", na=False)] = "Block"
    return out


def transform(raw: pd.DataFrame, season: str) -> pd.DataFrame:
    df = raw.assign(clock_seconds=clock_to_seconds(raw["clock"]))
    df = df.sort_values(
        ["gameId", "period", "clock_seconds", "actionNumber"], ascending=[True, True, False, True]
    ).reset_index(drop=True)
    secondary = df["actionType"].isna()
    desc = df["description"].fillna("")
    if "shotValue" not in df:
        df["shotValue"] = df["isFieldGoal"] * desc.str.contains("3PT").map({True: 3, False: 2})
    made_ft = df["actionType"].eq("Free Throw") & ~desc.str.startswith("MISS")
    points = df["actionType"].eq("Made Shot") * df["shotValue"] + made_ft.astype(int)

    return pd.DataFrame(
        {
            "game_id": df["gameId"].astype(str).str.zfill(10),
            "season": season,
            "event_index": df.groupby("gameId").cumcount(),
            "action_number": df["actionNumber"],
            "is_secondary": secondary,
            "period": df["period"],
            "clock_seconds": df["clock_seconds"],
            "team_id": df["teamId"].replace(0, np.nan).astype("Int64"),
            "player_id": df["personId"].replace(0, np.nan).astype("Int64"),
            "player_name": df["playerName"],
            "action_type": df["actionType"].where(~secondary, _secondary_type(desc)),
            "sub_type": df["subType"],
            "description": df["description"],
            "shot_result": df["shotResult"],
            "is_field_goal": df["isFieldGoal"].astype(bool),
            "shot_value": df["shotValue"],
            "shot_distance": df["shotDistance"],
            "x": df["xLegacy"],
            "y": df["yLegacy"],
            "location": df["location"],
            "score_home": df["scoreHome"].astype("Int64"),
            "score_away": df["scoreAway"].astype("Int64"),
            "points": points.astype(int),
        }
    )


def fetch_games(game_ids: list[str], season: str) -> pd.DataFrame:
    from nba_api.stats.endpoints import playbyplayv3

    from data.sources.nba_stats import _cached

    frames = [
        _cached(
            f"pbp_v3_{gid}",
            lambda gid=gid: playbyplayv3.PlayByPlayV3(game_id=gid, timeout=60),
            refresh=False,
        )
        for gid in game_ids
    ]
    raw = pd.concat(frames, ignore_index=True)
    raw["gameId"] = raw["gameId"].astype(int)
    for col in ("scoreHome", "scoreAway"):
        raw[col] = pd.to_numeric(raw[col].replace("", np.nan))
    for col in ("actionType", "subType", "shotResult", "playerName", "description", "location"):
        raw[col] = raw[col].replace("", np.nan)
    return transform(raw, season)


def load_season(season: str, refresh: bool = False) -> pd.DataFrame:
    with tarfile.open(archive_path(season, refresh)) as tar:
        member = tar.getmembers()[0]
        raw = pd.read_csv(tar.extractfile(member), low_memory=False)
    return transform(raw, season)
