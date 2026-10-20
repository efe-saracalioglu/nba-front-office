"""Build the DuckDB warehouse from NBA.com + Basketball-Reference.

    python -m data.build_warehouse                       # full history, cached fetches
    python -m data.build_warehouse --seasons 2023-24:2025-26 --skip-game-logs
    python -m data.build_warehouse --refresh-current     # re-pull rosters and contracts

Every step is idempotent: each slice is deleted and re-inserted.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd
from nba_api.stats.static import teams as static_teams

from data import config, db, quality
from data.crosswalk import build_crosswalk, match_by_name
from data.sources import bbref, nba_stats

log = logging.getLogger("etl")

BASE_COLS = {
    "PLAYER_ID": "player_id", "PLAYER_NAME": "player_name", "TEAM_ID": "team_id",
    "TEAM_ABBREVIATION": "team_abbreviation", "AGE": "age", "GP": "gp", "MIN": "min",
    "PTS": "pts", "REB": "reb", "OREB": "oreb", "DREB": "dreb", "AST": "ast", "STL": "stl",
    "BLK": "blk", "TOV": "tov", "PF": "pf", "FGM": "fgm", "FGA": "fga", "FG3M": "fg3m",
    "FG3A": "fg3a", "FTM": "ftm", "FTA": "fta", "PLUS_MINUS": "plus_minus",
}  # fmt: skip
ADV_COLS = {
    "OFF_RATING": "off_rating", "DEF_RATING": "def_rating", "NET_RATING": "net_rating",
    "AST_PCT": "ast_pct", "OREB_PCT": "oreb_pct", "DREB_PCT": "dreb_pct", "REB_PCT": "reb_pct",
    "TM_TOV_PCT": "tov_pct", "EFG_PCT": "efg_pct", "TS_PCT": "ts_pct", "USG_PCT": "usg_pct",
    "PACE": "pace", "PIE": "pie", "POSS": "poss",
}  # fmt: skip
LOG_COLS = {
    "GAME_ID": "game_id", "PLAYER_ID": "player_id", "PLAYER_NAME": "player_name",
    "TEAM_ID": "team_id", "TEAM_ABBREVIATION": "team_abbreviation", "GAME_DATE": "game_date",
    "MATCHUP": "matchup", "WL": "wl", "MIN": "min", "PTS": "pts", "REB": "reb", "OREB": "oreb",
    "DREB": "dreb", "AST": "ast", "STL": "stl", "BLK": "blk", "TOV": "tov", "PF": "pf",
    "FGM": "fgm", "FGA": "fga", "FG3M": "fg3m", "FG3A": "fg3a", "FTM": "ftm", "FTA": "fta",
    "PLUS_MINUS": "plus_minus",
}  # fmt: skip


def load_teams(con) -> None:
    rows = []
    for t in static_teams.get_teams():
        abbr, bbref_abbr, conf, div = config.TEAMS[t["id"]]
        rows.append(
            {
                "team_id": t["id"], "abbreviation": abbr, "bbref_abbreviation": bbref_abbr,
                "full_name": t["full_name"], "city": t["city"], "nickname": t["nickname"],
                "conference": conf, "division": div,
            }
        )  # fmt: skip
    db.replace_rows(con, "teams", pd.DataFrame(rows), source="nba_api.static")


def season_player_stats(season: str, refresh: bool) -> pd.DataFrame:
    base = nba_stats.player_stats(season, "Base", refresh)[list(BASE_COLS)].rename(
        columns=BASE_COLS
    )
    adv = nba_stats.player_stats(season, "Advanced", refresh)[["PLAYER_ID", *ADV_COLS]]
    adv = adv.rename(columns={"PLAYER_ID": "player_id", **ADV_COLS})
    return base.merge(adv, on="player_id", how="left").assign(season=season)


def season_team_stats(season: str, refresh: bool) -> pd.DataFrame:
    base = nba_stats.team_stats(season, "Base", refresh)
    adv = nba_stats.team_stats(season, "Advanced", refresh)
    df = base[["TEAM_ID", "GP", "W", "L", "W_PCT", "PTS", "PLUS_MINUS"]].merge(
        adv[["TEAM_ID", "OFF_RATING", "DEF_RATING", "NET_RATING", "PACE"]], on="TEAM_ID"
    )
    df.columns = [c.lower() for c in df.columns]
    return df.assign(season=season)


def season_game_logs(season: str, refresh: bool) -> pd.DataFrame:
    df = nba_stats.game_logs(season, refresh)[list(LOG_COLS)].rename(columns=LOG_COLS)
    df["game_date"] = pd.to_datetime(df["game_date"]).dt.date
    return df.assign(season=season)


def current_rosters(season: str, refresh: bool) -> pd.DataFrame:
    frames = [nba_stats.team_roster(tid, season, refresh) for tid in config.TEAMS]
    df = pd.concat(frames, ignore_index=True)
    # NBA.com flags two-way players with SUPPLEMENTAL_STATUS = 1.
    two_way = pd.to_numeric(df.get("SUPPLEMENTAL_STATUS"), errors="coerce").fillna(0) == 1
    return pd.DataFrame(
        {
            "team_id": df["TeamID"], "season": season, "player_id": df["PLAYER_ID"],
            "player_name": df["PLAYER"], "jersey": df["NUM"], "position": df["POSITION"],
            "birth_date": pd.to_datetime(df["BIRTH_DATE"], format="mixed", errors="coerce").dt.date,
            "experience": df["EXP"].astype(str), "how_acquired": df.get("HOW_ACQUIRED"),
            "is_two_way": two_way,
        }
    )  # fmt: skip


def build_players(stats, bios, advanced, rosters, xwalk) -> pd.DataFrame:
    latest_name = (
        pd.concat(
            [stats[["player_id", "player_name", "season"]], rosters[["player_id", "player_name"]]]
        )
        .fillna({"season": "9999"})
        .sort_values("season")
        .drop_duplicates("player_id", keep="last")[["player_id", "player_name"]]
    )
    bio = bios.sort_values("season").drop_duplicates("PLAYER_ID", keep="last")
    bio = pd.DataFrame(
        {
            "player_id": bio["PLAYER_ID"],
            "height_in": pd.to_numeric(bio["PLAYER_HEIGHT_INCHES"], errors="coerce"),
            "weight_lb": pd.to_numeric(bio["PLAYER_WEIGHT"], errors="coerce"),
            "country": bio["COUNTRY"], "college": bio["COLLEGE"],
            "draft_year": pd.to_numeric(bio["DRAFT_YEAR"], errors="coerce"),
            "draft_round": pd.to_numeric(bio["DRAFT_ROUND"], errors="coerce"),
            "draft_number": pd.to_numeric(bio["DRAFT_NUMBER"], errors="coerce"),
        }
    )  # fmt: skip
    pos = advanced.sort_values("season").drop_duplicates("player_id", keep="last")[
        ["player_id", "position"]
    ]
    births = rosters[["player_id", "birth_date"]].drop_duplicates("player_id")
    out = (
        latest_name.merge(xwalk[["player_id", "bbref_id"]], on="player_id", how="left")
        .merge(bio, on="player_id", how="left")
        .merge(pos, on="player_id", how="left")
        .merge(births, on="player_id", how="left")
    )
    roster_pos = rosters.drop_duplicates("player_id").set_index("player_id")["position"]
    out["position"] = out["position"].fillna(out["player_id"].map(roster_pos))
    for col in ("height_in", "weight_lb", "draft_year", "draft_round", "draft_number"):
        out[col] = out[col].astype("Int64")
    return out


def build_contracts(raw: pd.DataFrame, xwalk: pd.DataFrame, rosters, players) -> pd.DataFrame:
    df = raw.merge(xwalk[["bbref_id", "player_id"]], on="bbref_id", how="left")
    missing = df[df.player_id.isna()]
    if len(missing):
        # Rookies and returning players have no stats row yet; fall back to names.
        pool = pd.concat(
            [rosters[["player_id", "player_name"]], players[["player_id", "player_name"]]]
        )
        names = match_by_name(missing, pool).set_index("bbref_id")["player_id"]
        df["player_id"] = df["player_id"].fillna(df["bbref_id"].map(names))
    df["team_id"] = df["bbref_team"].map(config.BBREF_TO_TEAM_ID)
    df["player_id"] = df["player_id"].astype("Int64")
    return df.drop(columns="bbref_team")


def load_draft_picks(con, seed: Path) -> None:
    if not seed.exists():
        log.warning("no draft pick seed at %s; draft_picks stays empty", seed)
        return
    db.replace_rows(con, "draft_picks", pd.read_csv(seed), source=str(seed.name))


def build(
    db_path: Path,
    seasons: list[str],
    skip_game_logs: bool = False,
    refresh_current: bool = False,
) -> None:
    con = db.connect(db_path)
    db.create_schema(con)
    load_teams(con)

    stats, bios, advanced = [], [], []
    for season in seasons:
        log.info("season %s", season)
        s = season_player_stats(season, refresh=False)
        db.replace_rows(con, "player_season_stats", s, f"season = '{season}'", "nba_api")
        stats.append(s)
        bios.append(nba_stats.player_bio(season).assign(season=season))
        advanced.append(bbref.fetch_advanced(season))
        db.replace_rows(
            con, "team_season_stats", season_team_stats(season, False), f"season = '{season}'"
        )
        if not skip_game_logs:
            db.replace_rows(
                con, "player_game_logs", season_game_logs(season, False), f"season = '{season}'"
            )

    stats_df = pd.concat(stats, ignore_index=True)
    adv_df = pd.concat(advanced, ignore_index=True)
    xwalk = build_crosswalk(adv_df, stats_df)
    log.info("crosswalk: %s", xwalk.method.value_counts().to_dict())

    adv_matched = adv_df.merge(xwalk[["bbref_id", "player_id"]], on="bbref_id")
    adv_matched = adv_matched.drop_duplicates(subset=["player_id", "season"])
    db.replace_rows(
        con,
        "player_season_advanced",
        adv_matched,
        "season IN ({})".format(", ".join(f"'{s}'" for s in seasons)),
        "basketball-reference",
    )

    rosters = current_rosters(config.CURRENT_SEASON, refresh_current)
    db.replace_rows(con, "rosters", rosters, f"season = '{config.CURRENT_SEASON}'", "nba_api")

    players = build_players(
        stats_df, pd.concat(bios, ignore_index=True), adv_matched, rosters, xwalk
    )
    db.replace_rows(con, "players", players, source="nba_api+bbref")

    contracts = build_contracts(bbref.fetch_contracts(refresh_current), xwalk, rosters, players)
    db.replace_rows(con, "contracts", contracts, source="basketball-reference")

    load_draft_picks(con, config.DATA_DIR / "seed" / "draft_picks.csv")

    problems = quality.run_checks(con)
    for p in problems:
        log.warning("quality: %s", p)
    log.info("done: %s (%d quality warnings)", db_path, len(problems))
    con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", type=Path, default=config.default_db_path())
    parser.add_argument(
        "--seasons",
        default=f"{config.FIRST_SEASON}:{config.LAST_COMPLETED_SEASON}",
        help="first:last, e.g. 2015-16:2025-26",
    )
    parser.add_argument("--skip-game-logs", action="store_true")
    parser.add_argument("--refresh-current", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    first, last = args.seasons.split(":")
    build(args.db, config.season_range(first, last), args.skip_game_logs, args.refresh_current)


if __name__ == "__main__":
    main()
