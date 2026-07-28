"""
Day-ahead price forecasting for rolling-horizon dispatch.

The point of this module is not forecast accuracy for its own sake. It is to make
the backtest honest: an optimiser that sees realised prices earns a number no
operator can achieve. What matters is the *transmission* from forecast quality to
revenue, which is reported as the capture rate.

Leakage discipline, enforced structurally rather than by care:
  - every feature is built from lags, so a feature at t cannot contain information
    from t or later
  - the model is refit on an expanding window that ends strictly before the
    forecast origin
  - realised prices are used only for settlement, never inside the optimiser

One limit of that discipline is worth stating because it is not obvious. Each forecast
is day-ahead: the features for period t use prices up to t minus one day. That is
self-consistent for the forecast itself, but the backtest optimises over a 48-hour
window, and the forecasts for the second half of that window were built from prices
that had not yet occurred when the window began. Only the first half is executed, so
the contamination sits in the horizon padding rather than in the decisions themselves,
but it is a look-ahead and it is measured rather than assumed small — see the note in
the README. Removing it properly needs a genuine multi-horizon forecaster, in which the
forecast for every period in the window is conditioned only on data available when the
window opens; that has not been built.

Two forecasters are provided so that the revenue effect can be attributed to
forecast skill rather than to the presence of a forecaster:
  persistence  — yesterday's price at the same settlement period. The naive
                 baseline that any model must beat to justify itself.
  gbm          — LightGBM on calendar and lag features.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

LAGS = [48, 49, 96, 336]          # 1 day, 1 day +30min, 2 days, 1 week (half-hourly)
ROLLS = [48, 336]


def build_features(df: pd.DataFrame, price_col: str = "price") -> pd.DataFrame:
    """Lag/calendar features. All strictly backward-looking."""
    d = df.copy().reset_index(drop=True)
    d["settlement_period"] = d["settlement_period"].astype(int)
    ts = pd.to_datetime(d["start_time"], utc=True)
    d["dow"] = ts.dt.dayofweek
    d["month"] = ts.dt.month
    d["is_weekend"] = (d.dow >= 5).astype(int)
    d["hour"] = ts.dt.hour + ts.dt.minute / 60.0
    for L in LAGS:
        d[f"lag_{L}"] = d[price_col].shift(L)
    for R in ROLLS:
        # shift(48) first so the window ends at least one day before t
        d[f"roll_mean_{R}"] = d[price_col].shift(48).rolling(R).mean()
        d[f"roll_std_{R}"] = d[price_col].shift(48).rolling(R).std()
    d["lag_diff"] = d["lag_48"] - d["lag_96"]
    return d


FEATURES = (["settlement_period", "dow", "month", "is_weekend", "hour", "lag_diff"]
            + [f"lag_{L}" for L in LAGS]
            + [f"roll_mean_{R}" for R in ROLLS] + [f"roll_std_{R}" for R in ROLLS])


@dataclass
class Forecaster:
    kind: str = "gbm"                 # "gbm" | "persistence"
    retrain_every_days: int = 7
    min_train_periods: int = 48 * 60  # ~2 months before the first forecast
    price_col: str = "price"

    def run(self, df: pd.DataFrame) -> pd.DataFrame:
        """Produce out-of-sample forecasts for every period after the warm-up.

        Returns the input frame with a `forecast` column; rows before the warm-up
        are dropped so the backtest never runs on in-sample predictions.
        """
        d = build_features(df, self.price_col)
        n = len(d)
        start = max(self.min_train_periods, max(LAGS) + max(ROLLS) + 48)
        fc = np.full(n, np.nan)

        if self.kind == "persistence":
            fc[start:] = d["lag_48"].to_numpy()[start:]
            d["forecast"] = fc
            return d.iloc[start:].dropna(subset=["forecast"]).reset_index(drop=True)

        import lightgbm as lgb
        step = self.retrain_every_days * 48
        model = None
        for origin in range(start, n, step):
            train = d.iloc[:origin].dropna(subset=FEATURES + [self.price_col])
            if len(train) < 500:
                continue
            # `subsample` is deliberately absent: LightGBM ignores it unless
            # `subsample_freq` is also set, and `verbose=-1` hides the warning, so
            # passing it declared a behaviour the model never had. Setting both would
            # change every number in v2, so the parameter is dropped rather than
            # quietly enabled.
            model = lgb.LGBMRegressor(
                n_estimators=400, learning_rate=0.05, num_leaves=31,
                min_child_samples=30, colsample_bytree=0.9,
                verbose=-1, random_state=42)
            model.fit(train[FEATURES], train[self.price_col])
            stop = min(origin + step, n)
            block = d.iloc[origin:stop]
            ok = block[FEATURES].notna().all(axis=1)
            if ok.any():
                fc[origin:stop][ok.to_numpy()] = model.predict(block.loc[ok, FEATURES])
        d["forecast"] = fc
        return d.iloc[start:].dropna(subset=["forecast"]).reset_index(drop=True)


def skill(df: pd.DataFrame, price_col: str = "price", fc_col: str = "forecast") -> dict:
    """Accuracy plus the metric that actually matters for a battery.

    A battery earns the spread, not the level, so directional accuracy of the
    period-to-period change is reported alongside MAE and RMSE.
    """
    a = df[price_col].to_numpy(float)
    f = df[fc_col].to_numpy(float)
    err = f - a
    da = np.diff(a)
    dfc = np.diff(f)
    same_dir = np.mean(np.sign(da) == np.sign(dfc))
    # daily spread: does the forecast rank the cheap and expensive periods correctly
    tmp = df.assign(_a=a, _f=f, _d=pd.to_datetime(df.start_time, utc=True).dt.date)
    rank_corr = tmp.groupby("_d").apply(
        lambda g: g["_a"].corr(g["_f"], method="spearman"), include_groups=False)
    return {
        "mae": float(np.mean(np.abs(err))),
        "rmse": float(np.sqrt(np.mean(err ** 2))),
        "bias": float(np.mean(err)),
        "direction_accuracy": float(same_dir),
        "within_day_rank_corr_median": float(np.nanmedian(rank_corr)),
        "n": int(len(df)),
    }
