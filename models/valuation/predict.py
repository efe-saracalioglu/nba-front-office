from __future__ import annotations

import argparse
import json
from functools import cache
from pathlib import Path

import duckdb
import joblib
import numpy as np
import pandas as pd
import shap

from data import db
from data.config import season_label
from models.valuation.features import FEATURES, build_frame
from rules.season import load_season

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
STAT_NAMES = {
    "per": "PER",
    "ts_pct": "true shooting",
    "fg3a_rate": "three-point attempt rate",
    "fta_rate": "free-throw rate",
    "orb_pct": "offensive rebounding",
    "drb_pct": "defensive rebounding",
    "trb_pct": "rebounding",
    "ast_pct": "assist rate",
    "stl_pct": "steal rate",
    "blk_pct": "block rate",
    "tov_pct": "turnover rate",
    "usg_pct": "usage",
    "ws_per_48": "WS/48",
    "obpm": "offensive BPM",
    "dbpm": "defensive BPM",
    "bpm": "BPM",
    "ws_82": "Win Shares",
    "minute_share": "minutes share",
    "game_share": "games played share",
}
FEATURE_LABELS = {
    "ws_82": "Win Shares last season",
    "marcel_ws48": "3-year weighted WS/48",
    "age": "age",
    "age_sq": "age",
    "minute_share": "share of team minutes",
    "game_share": "games played share",
    "start_share": "games started share",
    "vorp_82": "VORP last season",
    "years_in_league": "years in league",
    "draft_number": "draft position",
    "marcel_minutes": "projected minutes",
    "pie": "player impact estimate",
    "net_rating": "on-court net rating",
    "minute_share_delta": "change in minutes share",
    "ws48_delta": "change in WS/48",
    "bpm_delta": "change in BPM",
    "height_in": "height",
    "weight_lb": "weight",
    "seasons_of_history": "seasons of history",
}


def feature_label(name: str) -> str:
    if name in FEATURE_LABELS:
        return FEATURE_LABELS[name]
    if name.startswith("z_"):
        return f"{STAT_NAMES.get(name[2:], name[2:])} vs league"
    for k, when in (("_lag1", "two seasons ago"), ("_lag2", "three seasons ago")):
        if name.endswith(k):
            return f"{STAT_NAMES.get(name[: -len(k)], name[: -len(k)])} {when}"
    return name


@cache
def load_artifacts(path: Path = ARTIFACTS) -> tuple[dict, dict]:
    models = joblib.load(path / "valuation.joblib")
    meta = json.loads((path / "valuation_meta.json").read_text(encoding="utf-8"))
    return models, meta


def latest_inputs(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    frame = build_frame(con)
    return frame[frame["year"] == frame["year"].max()].reset_index(drop=True)


def _factors(contribs: np.ndarray, values: pd.Series, k: int = 5) -> list[dict]:
    merged: dict[str, float] = {}
    for name, c in zip(FEATURES, contribs, strict=True):
        label = feature_label(name)
        merged[label] = merged.get(label, 0.0) + float(c)
    top = sorted(merged.items(), key=lambda kv: -abs(kv[1]))[:k]
    return [{"factor": label, "effect_ws": round(effect, 2)} for label, effect in top]


def project(inputs: pd.DataFrame, models: dict) -> pd.DataFrame:
    X = inputs[FEATURES]
    margin = models["conformal_margin"]
    point = models["point"].predict(X)
    lo = np.minimum(models["p10"].predict(X) - margin, point)
    hi = np.maximum(models["p90"].predict(X) + margin, point)
    contribs = shap.TreeExplainer(models["point"]).shap_values(X)
    out = inputs[["player_id", "player_name", "season", "age"]].copy()
    out["projected_ws"], out["ws_p10"], out["ws_p90"] = point, lo, hi
    out["top_factors"] = [json.dumps(_factors(contribs[i], X.iloc[i])) for i in range(len(X))]
    return out


def attach_value(proj: pd.DataFrame, con: duckdb.DuckDBPyConnection, season: str) -> pd.DataFrame:
    cfg = load_season(season)
    salaries = con.execute(
        """SELECT r.player_id, r.team_id, c.salary FROM rosters r
           LEFT JOIN contracts c ON c.player_id = r.player_id AND c.season = r.season AND c.team_id = r.team_id
           WHERE r.season = ? AND NOT r.is_two_way""",
        [season],
    ).df()
    out = proj.merge(salaries, on="player_id", how="left")
    priced = out[out["salary"].notna()]
    above_min = (priced["salary"] - cfg.minimum_salary).clip(lower=0).sum()
    dollars_per_ws = above_min / priced["projected_ws"].clip(lower=0).sum()
    out["market_value"] = (
        cfg.minimum_salary + dollars_per_ws * out["projected_ws"].clip(lower=0)
    ).round()
    out["surplus_value"] = out["market_value"] - out["salary"]
    out.attrs["dollars_per_ws"] = dollars_per_ws
    return out


def build_projections(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    models, meta = load_artifacts()
    inputs = latest_inputs(con)
    based_on = inputs["season"].iloc[0]
    target_season = season_label(int(based_on[:4]) + 2)
    proj = attach_value(project(inputs, models), con, target_season)
    proj["based_on_season"] = based_on
    proj["projected_season"] = target_season
    proj["age_next"] = proj["age"] + 1
    proj["model_version"] = meta["trained_at"]
    proj["team_id"] = proj["team_id"].astype("Int64")
    for col in ("salary", "market_value", "surplus_value"):
        proj[col] = proj[col].astype("Int64")
    cols = ["player_id", "player_name", "team_id", "based_on_season", "projected_season", "age_next",
            "projected_ws", "ws_p10", "ws_p90", "salary", "market_value", "surplus_value", "top_factors",
            "model_version"]  # fmt: skip
    return proj[cols]


def predict_player(con: duckdb.DuckDBPyConnection, player_id: int) -> dict | None:
    row = con.execute("SELECT * FROM player_projections WHERE player_id = ?", [player_id]).df()
    if row.empty:
        return None
    rec = json.loads(row.to_json(orient="records"))[0]
    rec["top_factors"] = json.loads(rec["top_factors"])
    return rec


def main() -> None:
    parser = argparse.ArgumentParser(description="Write next-season projections to the warehouse")
    parser.add_argument("--db", type=Path, default=None)
    args = parser.parse_args()
    con = db.connect(args.db)
    db.create_schema(con)
    proj = build_projections(con)
    db.replace_rows(con, "player_projections", proj, source="models/valuation")
    con.close()
    print(f"{len(proj)} projections for {proj['projected_season'].iloc[0]}")


if __name__ == "__main__":
    main()
