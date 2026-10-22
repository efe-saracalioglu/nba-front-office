from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

import duckdb

from data import config, db

OUT = Path(__file__).resolve().parent / "exact.jsonl"
SEASONS = ["2021-22", "2022-23", "2023-24", "2024-25", "2025-26"]

LEADER_STATS = {
    "points per game (minimum 50 games)": ("round(pts / gp, 1)", "player_season_stats", "gp >= 50"),
    "assists per game (minimum 50 games)": (
        "round(ast / gp, 1)",
        "player_season_stats",
        "gp >= 50",
    ),
    "rebounds per game (minimum 50 games)": (
        "round(reb / gp, 1)",
        "player_season_stats",
        "gp >= 50",
    ),
    "Win Shares": ("round(ws, 1)", "player_season_advanced", "g >= 1"),
    "Box Plus/Minus (minimum 1,500 minutes)": (
        "round(bpm, 1)",
        "player_season_advanced",
        "mp >= 1500",
    ),
    "total three-pointers made": ("fg3m", "player_season_stats", "gp >= 1"),
}


def salt(rng: random.Random) -> str:
    return f"{rng.random():.12f}"


def one(con: duckdb.DuckDBPyConnection, sql: str, params: list | None = None):
    row = con.execute(sql, params or []).fetchone()
    return row if row else None


def leader(con, rng) -> dict:
    label, (expr, table, where) = rng.choice(list(LEADER_STATS.items()))
    season = rng.choice(SEASONS)
    name, value = one(
        con,
        f"SELECT player_name, {expr} AS v FROM {table} WHERE season = ? AND {where} ORDER BY v DESC LIMIT 1",
        [season],
    )
    return {"question": f"Who led the NBA in {label} in the {season} regular season?", "kind": "name",
            "answer": name, "context_value": value, "template": "leader"}  # fmt: skip


def player_average(con, rng) -> dict:
    season = rng.choice(SEASONS)
    name, gp, ppg = one(
        con,
        "SELECT player_name, gp, round(pts / gp, 1) FROM player_season_stats WHERE season = ? AND gp >= 50 AND pts / gp >= 15 ORDER BY hash(player_name || ?) LIMIT 1",
        [season, salt(rng)],
    )
    return {"question": f"How many points per game did {name} average in {season}?", "kind": "number",
            "answer": ppg, "tolerance": 0.15, "template": "player_average"}  # fmt: skip


def team_wins(con, rng) -> dict:
    season = rng.choice(SEASONS)
    team, w = one(
        con,
        "SELECT t.full_name, s.w FROM team_season_stats s JOIN teams t USING (team_id) WHERE season = ? ORDER BY hash(t.full_name || ?) LIMIT 1",
        [season, salt(rng)],
    )
    return {"question": f"How many regular-season games did the {team} win in {season}?", "kind": "number",
            "answer": w, "tolerance": 0, "template": "team_wins"}  # fmt: skip


def best_net_rating(con, rng) -> dict:
    season = rng.choice(SEASONS)
    team, abbr = one(
        con,
        "SELECT t.full_name, t.abbreviation FROM team_season_stats s JOIN teams t USING (team_id) WHERE season = ? ORDER BY net_rating DESC LIMIT 1",
        [season],
    )
    return {"question": f"Which team had the best net rating in {season}?", "kind": "team",
            "answer": team, "aliases": [abbr, team.split()[-1]], "template": "best_net_rating"}  # fmt: skip


def payroll(con, rng) -> dict:
    team, abbr, total = one(
        con,
        "SELECT t.full_name, t.abbreviation, sum(c.salary) FROM contracts c JOIN teams t USING (team_id) WHERE c.season = '2026-27' GROUP BY 1, 2 ORDER BY hash(t.full_name || ?) LIMIT 1",
        [salt(rng)],
    )
    return {"question": f"What is the {team}' total 2026-27 payroll in the contracts table, in dollars?", "kind": "money",
            "answer": int(total), "tolerance_pct": 0.01, "template": "payroll"}  # fmt: skip


def contract_salary(con, rng) -> dict:
    name, season, salary = one(
        con,
        "SELECT player_name, season, salary FROM contracts WHERE season IN ('2026-27', '2027-28') AND salary > 15000000 ORDER BY hash(player_name || season || ?) LIMIT 1",
        [salt(rng)],
    )
    return {"question": f"How much is {name} scheduled to be paid in the {season} season?", "kind": "money",
            "answer": int(salary), "tolerance_pct": 0.01, "template": "contract_salary"}  # fmt: skip


def pick_owner(con, rng) -> dict:
    team, year, owner_name, owner_abbr = one(
        con,
        """
        SELECT og.full_name, d.year, o.full_name, o.abbreviation FROM draft_picks d
        JOIN teams o ON o.team_id = d.owner_team_id JOIN teams og ON og.team_id = d.original_team_id
        WHERE d.round = 1 AND d.kind = 'acquired' ORDER BY hash(og.full_name || d.year || ?) LIMIT 1""",
        [salt(rng)],
    )
    return {"question": f"Which team currently owns the {team}' own {year} first-round pick?", "kind": "team",
            "answer": owner_name, "aliases": [owner_abbr, owner_name.split()[-1]], "template": "pick_owner"}  # fmt: skip


def games_over_40(con, rng) -> dict:
    name, n = one(
        con,
        "SELECT player_name, count(*) FILTER (WHERE pts >= 40) n FROM player_game_logs WHERE season = '2025-26' GROUP BY 1 HAVING n >= 1 ORDER BY hash(player_name || ?) LIMIT 1",
        [salt(rng)],
    )
    return {"question": f"In how many 2025-26 regular-season games did {name} score 40 or more points?", "kind": "number",
            "answer": n, "tolerance": 0, "template": "games_over_40"}  # fmt: skip


def count_25ppg(con, rng) -> dict:
    season = rng.choice(SEASONS)
    (n,) = one(
        con,
        "SELECT count(*) FROM player_season_stats WHERE season = ? AND gp >= 50 AND pts / gp >= 25",
        [season],
    )
    return {"question": f"How many players averaged at least 25 points per game in {season} (minimum 50 games)?", "kind": "number",
            "answer": n, "tolerance": 0, "template": "count_25ppg"}  # fmt: skip


def injury_status(con, rng) -> dict:
    name, status = one(
        con,
        "SELECT r.player_name, i.status FROM injuries i JOIN rosters r USING (player_id) ORDER BY hash(r.player_name || ?) LIMIT 1",
        [salt(rng)],
    )
    return {"question": f"What is {name}'s current injury status?", "kind": "text",
            "answer": status, "aliases": [status.replace("-", " ")], "template": "injury_status"}  # fmt: skip


def top_projection(con, rng) -> dict:
    pos = rng.choice(["C", "PG", "SF", "PF", "SG"])
    name, ws = one(
        con,
        "SELECT j.player_name, round(j.projected_ws, 1) FROM player_projections j JOIN players p USING (player_id) WHERE p.position = ? ORDER BY j.projected_ws DESC LIMIT 1",
        [pos],
    )
    return {"question": f"Which player listed at position {pos} has the highest projected Win Shares for 2026-27?", "kind": "name",
            "answer": name, "context_value": ws, "template": "top_projection"}  # fmt: skip


def clutch(con, rng) -> dict:
    name, pts = one(
        con,
        """SELECT p.player_name, sum(e.points) pts FROM pbp_events e JOIN players p USING (player_id)
                           WHERE e.season = '2025-26' AND e.period >= 4 AND e.clock_seconds <= 300 GROUP BY 1 ORDER BY pts DESC LIMIT 1""",
    )
    return {"question": "Who scored the most total points in the final five minutes of the fourth quarter or overtime during the 2025-26 regular season?",
            "kind": "name", "answer": name, "context_value": pts, "template": "clutch"}  # fmt: skip


TEMPLATES = [leader, player_average, team_wins, best_net_rating, payroll, contract_salary, pick_owner,
             games_over_40, count_25ppg, injury_status, top_projection, clutch]  # fmt: skip


def build(con, n: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    seen, out = set(), []
    while len(out) < n:
        for template in TEMPLATES:
            if len(out) >= n:
                break
            item = template(con, rng)
            if item["question"] in seen:
                continue
            seen.add(item["question"])
            out.append(item)
    return out


def answerable_on_sample(item: dict, sample: duckdb.DuckDBPyConnection) -> bool:
    season_tables = {"leader", "player_average", "team_wins", "best_net_rating", "count_25ppg"}
    if item["template"] in ("clutch", "games_over_40"):
        return False
    if item["template"] in season_tables:
        seasons = {
            r[0]
            for r in sample.execute("SELECT DISTINCT season FROM player_season_stats").fetchall()
        }
        return any(s in item["question"] for s in seasons)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the exact-answer layer of NBA-Bench")
    parser.add_argument("--n", type=int, default=84)
    parser.add_argument("--seed", type=int, default=11)
    args = parser.parse_args()
    con = db.connect(read_only=True)
    sample = db.connect(config.SAMPLE_DB, read_only=True)
    items = build(con, args.n, args.seed)
    with OUT.open("w", encoding="utf-8") as f:
        for i, item in enumerate(items, 1):
            item = {"id": f"exact-{i:03d}", **item, "sample_ok": answerable_on_sample(item, sample)}
            f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")
    print(f"wrote {len(items)} questions to {OUT}")


if __name__ == "__main__":
    main()
