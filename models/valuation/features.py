from __future__ import annotations

import duckdb
import numpy as np
import pandas as pd

MIN_MINUTES = 250
SEASON_GAMES = 82

RATE_STATS = [
    "per",
    "ts_pct",
    "fg3a_rate",
    "fta_rate",
    "orb_pct",
    "drb_pct",
    "trb_pct",
    "ast_pct",
    "stl_pct",
    "blk_pct",
    "tov_pct",
    "usg_pct",
    "ws_per_48",
    "obpm",
    "dbpm",
    "bpm",
]
LAG_STATS = [
    "ws_82",
    "ws_per_48",
    "bpm",
    "obpm",
    "dbpm",
    "minute_share",
    "game_share",
    "usg_pct",
    "ts_pct",
]

FEATURES = (
    [
        "age",
        "age_sq",
        "height_in",
        "weight_lb",
        "draft_number",
        "years_in_league",
        "seasons_of_history",
    ]
    + ["ws_82", "minute_share", "game_share", "start_share", "net_rating", "pie", "vorp_82"]
    + [f"z_{s}" for s in RATE_STATS]
    + [f"{s}_lag{k}" for s in LAG_STATS for k in (1, 2)]
    + ["ws48_delta", "bpm_delta", "minute_share_delta", "marcel_ws48", "marcel_minutes"]
)
TARGET = "target_ws_82"


def _season_year(season: pd.Series) -> pd.Series:
    return season.str[:4].astype(int) + 1


def load_seasons(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.execute(
        """
        WITH games AS (SELECT season, max(gp) AS team_games FROM team_season_stats GROUP BY 1)
        SELECT a.player_id, a.season, a.player_name, a.position, a.age, a.g, a.gs, a.mp,
               a.per, a.ts_pct, a.fg3a_rate, a.fta_rate, a.orb_pct, a.drb_pct, a.trb_pct,
               a.ast_pct, a.stl_pct, a.blk_pct, a.tov_pct, a.usg_pct, a.ows, a.dws, a.ws,
               a.ws_per_48, a.obpm, a.dbpm, a.bpm, a.vorp,
               s.net_rating, s.pie, s.team_abbreviation,
               p.height_in, p.weight_lb, p.draft_year, p.draft_number,
               g.team_games
        FROM player_season_advanced a
        JOIN player_season_stats s USING (player_id, season)
        JOIN players p USING (player_id)
        JOIN games g USING (season)
        """
    ).df()
    df["year"] = _season_year(df["season"])
    scale = SEASON_GAMES / df["team_games"]
    df["ws_82"] = df["ws"] * scale
    df["vorp_82"] = df["vorp"] * scale
    df["minute_share"] = df["mp"] / (df["team_games"] * 48)
    df["game_share"] = df["g"] / df["team_games"]
    df["start_share"] = df["gs"] / df["g"].clip(lower=1)
    return df


def _zscores(df: pd.DataFrame) -> pd.DataFrame:
    qualified = df[df["mp"] >= MIN_MINUTES]
    stats = qualified.groupby("season")[RATE_STATS].agg(["mean", "std"])
    out = df.copy()
    for s in RATE_STATS:
        mean = out["season"].map(stats[(s, "mean")])
        std = out["season"].map(stats[(s, "std")]).replace(0, np.nan)
        out[f"z_{s}"] = (out[s] - mean) / std
    return out


def _lags(df: pd.DataFrame) -> pd.DataFrame:
    base = df[["player_id", "year", "mp", *LAG_STATS]]
    out = df.copy()
    for k in (1, 2):
        lagged = base.assign(year=base["year"] + k).rename(
            columns={c: f"{c}_lag{k}" for c in ["mp", *LAG_STATS]}
        )
        out = out.merge(lagged, on=["player_id", "year"], how="left")
    first_year = df.groupby("player_id")["year"].min()
    out["seasons_of_history"] = out["year"] - out["player_id"].map(first_year) + 1
    return out


def _marcel_inputs(df: pd.DataFrame) -> pd.DataFrame:
    w = [(5, ""), (4, "_lag1"), (3, "_lag2")]
    num = sum(
        weight * df[f"ws_per_48{sfx}"].fillna(0) * df[f"mp{sfx}"].fillna(0) for weight, sfx in w
    )
    den = sum(weight * df[f"mp{sfx}"].fillna(0) for weight, sfx in w)
    regression_minutes, league_ws48 = 1000, 0.100
    out = df.copy()
    out["marcel_ws48"] = (num + regression_minutes * league_ws48) / (den + regression_minutes)
    out["marcel_minutes"] = (0.5 * df["mp"] + 0.1 * df["mp_lag1"].fillna(0) + 600).clip(upper=3000)
    return out


def build_frame(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = load_seasons(con)
    df = _zscores(df)
    df = _lags(df)
    df = _marcel_inputs(df)
    df["age_sq"] = df["age"] ** 2
    df["draft_number"] = df["draft_number"].fillna(61)
    debut = df["draft_year"].where(df["draft_year"].notna(), df["year"] - df["seasons_of_history"])
    df["years_in_league"] = df["year"] - 1 - debut
    df["ws48_delta"] = df["ws_per_48"] - df["ws_per_48_lag1"]
    df["bpm_delta"] = df["bpm"] - df["bpm_lag1"]
    df["minute_share_delta"] = df["minute_share"] - df["minute_share_lag1"]

    target = df[["player_id", "year", "ws_82"]].rename(columns={"ws_82": TARGET})
    target["year"] -= 1
    df = df.merge(target, on=["player_id", "year"], how="left")
    return df[df["mp"] >= MIN_MINUTES].reset_index(drop=True)


def training_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame[TARGET].notna()].reset_index(drop=True)
