import numpy as np
import pandas as pd
import pytest

from data import config, db
from models.valuation.baselines import marcel
from models.valuation.features import FEATURES, TARGET, build_frame
from models.valuation.predict import _factors, feature_label
from models.valuation.train import conformal_margin


def test_conformal_margin_reaches_target_coverage():
    rng = np.random.default_rng(0)
    y = rng.normal(size=2000)
    lo, hi = np.full_like(y, -0.5), np.full_like(y, 0.5)
    m = conformal_margin(y, lo, hi, coverage=0.8)
    assert np.mean((y >= lo - m) & (y <= hi + m)) >= 0.8
    assert 0.7 < m < 0.85


def test_conformal_margin_negative_when_intervals_too_wide():
    y = np.zeros(100)
    assert conformal_margin(y, np.full(100, -5.0), np.full(100, 5.0)) < 0


def test_marcel_regresses_to_league_mean_and_ages():
    row = pd.DataFrame(
        {"marcel_ws48": [0.100, 0.100], "marcel_minutes": [2000, 2000], "age": [27, 33]}
    )
    young, old = marcel(row)
    assert young == pytest.approx(0.100 * 2000 / 48)
    assert old < young


def test_feature_labels_are_readable():
    assert feature_label("z_per") == "PER vs league"
    assert feature_label("ws_82_lag1") == "Win Shares two seasons ago"
    assert feature_label("age_sq") == "age"


def test_factors_merge_age_terms():
    contribs = np.zeros(len(FEATURES))
    contribs[FEATURES.index("age")] = -0.4
    contribs[FEATURES.index("age_sq")] = -0.3
    contribs[FEATURES.index("ws_82")] = 1.0
    out = _factors(contribs, pd.Series(dtype=float), k=2)
    assert out == [
        {"factor": "Win Shares last season", "effect_ws": 1.0},
        {"factor": "age", "effect_ws": -0.7},
    ]


@pytest.fixture(scope="module")
def frame():
    if not config.SAMPLE_DB.exists():
        pytest.skip("sample warehouse missing")
    con = db.connect(config.SAMPLE_DB, read_only=True)
    out = build_frame(con)
    con.close()
    return out


def test_features_only_use_past_and_target_uses_next_season(frame):
    by_key = frame.set_index(["player_id", "year"])
    sample = frame[frame["ws_82_lag1"].notna() & frame[TARGET].notna()].head(25)
    for _, r in sample.iterrows():
        prev = (
            by_key.loc[(r.player_id, r.year - 1)]
            if (r.player_id, r.year - 1) in by_key.index
            else None
        )
        nxt = (
            by_key.loc[(r.player_id, r.year + 1)]
            if (r.player_id, r.year + 1) in by_key.index
            else None
        )
        if prev is not None:
            assert r.ws_82_lag1 == pytest.approx(prev.ws_82)
        if nxt is not None:
            assert r[TARGET] == pytest.approx(nxt.ws_82)


def test_every_feature_is_present(frame):
    assert set(FEATURES) <= set(frame.columns)
    assert frame["age"].notna().all()
