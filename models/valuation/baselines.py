from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import RidgeCV
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

PEAK_AGE = 27
AGING_WS48_PER_YEAR = 0.004


def persistence(df: pd.DataFrame) -> np.ndarray:
    return df["ws_82"].to_numpy()


def marcel(df: pd.DataFrame) -> np.ndarray:
    ws48 = df["marcel_ws48"] + AGING_WS48_PER_YEAR * (PEAK_AGE - df["age"])
    return (ws48 * df["marcel_minutes"] / 48).to_numpy()


def ridge(features: list[str]):
    return make_pipeline(
        SimpleImputer(strategy="median"),
        StandardScaler(),
        RidgeCV(alphas=np.logspace(-2, 3, 20)),
    )
