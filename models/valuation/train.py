from __future__ import annotations

import argparse
import json
import random
from datetime import UTC, datetime
from pathlib import Path

import joblib
import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from data import db
from models.valuation import baselines
from models.valuation.features import FEATURES, TARGET, build_frame, training_rows

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
VALID_YEARS = (2022, 2023)
TEST_YEARS = (2024, 2025)
CV_YEARS = (2016, 2017, 2018, 2019, 2020, 2021)
QUANTILES = (0.1, 0.9)
SEED = 42

COVERAGE = QUANTILES[1] - QUANTILES[0]

SEARCH_SPACE = {
    "objective": ["regression", "huber", "regression_l1"],
    "num_leaves": [7, 15, 31],
    "learning_rate": [0.02, 0.03, 0.05],
    "n_estimators": [300, 600, 900],
    "min_child_samples": [20, 40, 80],
    "subsample": [0.7, 0.85, 1.0],
    "colsample_bytree": [0.5, 0.7, 0.9],
    "reg_lambda": [0.0, 1.0, 5.0],
}


def metrics(y: np.ndarray, pred: np.ndarray) -> dict:
    return {
        "mae": round(float(mean_absolute_error(y, pred)), 3),
        "rmse": round(float(np.sqrt(mean_squared_error(y, pred))), 3),
        "r2": round(float(r2_score(y, pred)), 3),
        "spearman": round(float(spearmanr(y, pred).statistic), 3),
    }


def lgbm(params: dict, quantile: float | None = None) -> lgb.LGBMRegressor:
    params = dict(params)
    if quantile is not None:
        params.update(objective="quantile", alpha=quantile)
    return lgb.LGBMRegressor(subsample_freq=1, random_state=SEED, verbose=-1, **params)


def fit_interval(train: pd.DataFrame, params: dict) -> tuple[lgb.LGBMRegressor, lgb.LGBMRegressor]:
    lo = lgbm(params, QUANTILES[0]).fit(train[FEATURES], train[TARGET])
    hi = lgbm(params, QUANTILES[1]).fit(train[FEATURES], train[TARGET])
    return lo, hi


def conformal_margin(
    y: np.ndarray, lo: np.ndarray, hi: np.ndarray, coverage: float = COVERAGE
) -> float:
    scores = np.maximum(lo - y, y - hi)
    n = len(scores)
    level = min(1.0, np.ceil((n + 1) * coverage) / n)
    return float(np.quantile(scores, level, method="higher"))


def time_cv_mae(df: pd.DataFrame, params: dict) -> float:
    errors = []
    for year in CV_YEARS:
        train, valid = df[df["year"] < year], df[df["year"] == year]
        model = lgbm(params).fit(train[FEATURES], train[TARGET])
        errors.append(mean_absolute_error(valid[TARGET], model.predict(valid[FEATURES])))
    return float(np.mean(errors))


def tune(df: pd.DataFrame, trials: int) -> tuple[dict, list[dict]]:
    rng = random.Random(SEED)
    history = []
    for _ in range(trials):
        params = {k: rng.choice(v) for k, v in SEARCH_SPACE.items()}
        history.append({"params": params, "cv_mae": round(time_cv_mae(df, params), 4)})
    best = min(history, key=lambda h: h["cv_mae"])
    return best["params"], sorted(history, key=lambda h: h["cv_mae"])


def evaluate(
    train: pd.DataFrame, holdout: pd.DataFrame, params: dict, interval: tuple, margin: float
) -> tuple[dict, pd.DataFrame]:
    y = holdout[TARGET].to_numpy()
    ridge = baselines.ridge(FEATURES).fit(train[FEATURES], train[TARGET])
    model = lgbm(params).fit(train[FEATURES], train[TARGET])
    preds = {
        "persistence": baselines.persistence(holdout),
        "marcel": baselines.marcel(holdout),
        "ridge": ridge.predict(holdout[FEATURES]),
        "lightgbm": model.predict(holdout[FEATURES]),
    }
    p10 = interval[0].predict(holdout[FEATURES]) - margin
    p90 = interval[1].predict(holdout[FEATURES]) + margin
    raw_cover = np.mean((y >= p10 + margin) & (y <= p90 - margin))
    result = {name: metrics(y, p) for name, p in preds.items()}
    result["interval"] = {
        "target_coverage": round(COVERAGE, 2),
        "raw_quantile_coverage": round(float(raw_cover), 3),
        "conformal_coverage": round(float(np.mean((y >= p10) & (y <= p90))), 3),
        "conformal_margin": round(margin, 3),
        "mean_width": round(float(np.mean(p90 - p10)), 3),
    }
    frame = holdout[["player_id", "player_name", "season", "age", "mp", "ws_82", TARGET]].copy()
    for name, p in preds.items():
        frame[f"pred_{name}"] = p
    frame["p10"], frame["p90"] = p10, p90
    return result, frame


def breakdown(frame: pd.DataFrame) -> dict:
    out = {}
    groups = {
        "age": pd.cut(frame["age"], [0, 23, 27, 31, 50], labels=["<=23", "24-27", "28-31", "32+"]),
        "minutes": pd.cut(
            frame["mp"], [0, 1000, 2000, 5000], labels=["250-1000", "1000-2000", "2000+"]
        ),
    }
    for name, key in groups.items():
        out[name] = {
            str(g): {
                "n": int(len(part)),
                "marcel_mae": round(
                    float(mean_absolute_error(part[TARGET], part["pred_marcel"])), 3
                ),
                "lightgbm_mae": round(
                    float(mean_absolute_error(part[TARGET], part["pred_lightgbm"])), 3
                ),
            }
            for g, part in frame.groupby(key, observed=True)
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the player valuation model")
    parser.add_argument("--trials", type=int, default=40)
    args = parser.parse_args()

    con = db.connect(read_only=True)
    frame = build_frame(con)
    con.close()
    rows = training_rows(frame)
    search = rows[rows["year"] < VALID_YEARS[0]]
    valid = rows[rows["year"].isin(VALID_YEARS)]
    dev = rows[rows["year"] < TEST_YEARS[0]]
    test = rows[rows["year"].isin(TEST_YEARS)]
    params, history = tune(search, args.trials)

    search_interval = fit_interval(search, params)
    margin_valid = conformal_margin(
        valid[TARGET].to_numpy(),
        search_interval[0].predict(valid[FEATURES]),
        search_interval[1].predict(valid[FEATURES]),
    )
    valid_result, _ = evaluate(search, valid, params, search_interval, margin_valid)
    dev_interval = fit_interval(dev, params)
    test_result, test_frame = evaluate(dev, test, params, dev_interval, margin_valid)
    margin_final = conformal_margin(
        test[TARGET].to_numpy(),
        dev_interval[0].predict(test[FEATURES]),
        dev_interval[1].predict(test[FEATURES]),
    )

    final_lo, final_hi = fit_interval(rows, params)
    final = {
        "point": lgbm(params).fit(rows[FEATURES], rows[TARGET]),
        "p10": final_lo,
        "p90": final_hi,
        "conformal_margin": margin_final,
    }
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(final, ARTIFACTS / "valuation.joblib")
    test_frame.to_parquet(ARTIFACTS / "test_predictions.parquet", index=False)
    meta = {
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": "next-season Win Shares scaled to 82 games",
        "features": FEATURES,
        "rows": len(rows),
        "train_seasons": [rows["season"].min(), rows["season"].max()],
        "valid_years": VALID_YEARS,
        "test_years": TEST_YEARS,
        "params": params,
        "conformal_margin": round(margin_final, 3),
        "tuning_top5": history[:5],
        "validation": valid_result,
        "test": test_result,
        "test_breakdown": breakdown(test_frame),
    }
    (ARTIFACTS / "valuation_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"params": params, "validation": valid_result, "test": test_result}, indent=2))


if __name__ == "__main__":
    main()
