"""v8b — how much narrower is a conditional forecast than the prices it predicts?

v2 records an anomaly that reads as a paradox: the LightGBM arm cycles *less* than the
naive persistence arm (425.5 against 450.8 EFC/yr) despite forecasting better on every
accuracy metric. The explanation is not accuracy but width. A conditional mean — or
median — is a shrunk object by construction, and a battery does not earn the level of a
price, it earns the spread. Hand the optimiser a flattened path and it sees fewer spreads
worth paying wear for.

What is measured here is the quantity dispatch actually depends on: the daily top-4
minus bottom-4 spread. Four half-hours is roughly what this 2-hour asset moves in one
direction per cycle, so it is the depth the marginal cycle is priced against — the
single-period top-bottom range would flatter every series equally and say less.

Persistence is included as the control that makes the point. It is a *worse* forecast on
MAE, but it is an actual price path shifted by a day, so its width is right by
construction. If width rather than accuracy drives cycling, persistence should look
undistorted here while LightGBM does not.

Reads the cached quantile forecasts from `v8_stochastic.py` stage one; no solving.

Run:  PYTHONPATH=src python3 scripts/v8b_shrinkage.py
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bess.data.elexon import market_index
from bess.forecast.price import Forecaster

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results"
CACHE = ROOT / "data" / "cache" / "v8_quantiles.parquet"
DEPTH = 4


def depth_spread(mat: np.ndarray, k: int = DEPTH) -> np.ndarray:
    """Mean of the k highest minus mean of the k lowest, per day."""
    s = np.sort(mat, axis=1)
    return s[:, -k:].mean(axis=1) - s[:, :k].mean(axis=1)


def main():
    if not CACHE.exists():
        raise SystemExit(f"missing {CACHE}; run v8_stochastic.py ... forecast first")
    d = pd.read_parquet(CACHE)
    d["day"] = pd.to_datetime(d.start_time, utc=True).dt.date

    # persistence over the same rows, as the width control
    raw = market_index(date(2024, 1, 1), date(2025, 12, 31)).dropna(
        subset=["price"]).reset_index(drop=True)
    pers = Forecaster(kind="persistence").run(raw)
    pers["day"] = pd.to_datetime(pers.start_time, utc=True).dt.date
    d = d.merge(pers[["start_time", "forecast"]].rename(columns={"forecast": "persistence"}),
                on="start_time", how="left").dropna(subset=["persistence"])

    n = d.groupby("day").size()
    full = set(n[n == 48].index)
    d = d[d.day.isin(full)]
    days = d.day.nunique()

    cols = {"realised": "price", "q50": "q50", "persistence": "persistence"}
    mats = {k: d[v].to_numpy(float).reshape(days, 48) for k, v in cols.items()}
    sp = {k: depth_spread(m) for k, m in mats.items()}

    base = sp["realised"]
    rows = []
    for k in ("realised", "q50", "persistence"):
        s = sp[k]
        rows.append({
            "series": k,
            "mean_daily_spread_GBP_per_MWh": round(float(s.mean()), 2),
            "sd_daily_spread": round(float(s.std(ddof=1)), 2),
            "ratio_of_means_to_realised": round(float(s.mean() / base.mean()), 3),
            "ratio_of_sds_to_realised": round(float(s.std(ddof=1) / base.std(ddof=1)), 3),
            "median_daily_ratio_to_realised": round(float(np.median(s / base)), 3),
            "days_narrower_than_realised_pct": round(float((s < base).mean() * 100), 1),
        })
        print(f"  {k:12s} mean {s.mean():7.2f}  sd {s.std(ddof=1):7.2f}"
              f"  mean ratio {s.mean()/base.mean():5.3f}  sd ratio "
              f"{s.std(ddof=1)/base.std(ddof=1):5.3f}")

    q50, per = rows[1], rows[2]
    summary = {
        "depth_k_half_hours": DEPTH,
        "days": int(days),
        "window": [str(d.day.min()), str(d.day.max())],
        "definition": ("daily spread = mean of the k highest prices minus mean of the k "
                       "lowest, k=4 half-hours, which is roughly the depth this 2-hour "
                       "asset moves in one direction per cycle"),
        "finding": (
            f"the median forecast's daily spread averages "
            f"{q50['mean_daily_spread_GBP_per_MWh']} against a realised "
            f"{rows[0]['mean_daily_spread_GBP_per_MWh']} "
            f"(ratio {q50['ratio_of_means_to_realised']}), and its day-to-day standard "
            f"deviation is {q50['ratio_of_sds_to_realised']} of the realised one. "
            f"Persistence, a worse forecast by MAE but an actual price path, is "
            f"undistorted at {per['ratio_of_means_to_realised']} and "
            f"{per['ratio_of_sds_to_realised']} — so the compression is a property of "
            f"conditional-mean forecasting, not of forecasting"),
        "table": rows,
    }
    pd.DataFrame(rows).to_csv(OUT / "v8_shrinkage.csv", index=False)
    (OUT / "v8_shrinkage.json").write_text(json.dumps(summary, indent=2))
    print(f"\n--- finding ---\n{summary['finding']}")
    print(f"\nwritten: {OUT/'v8_shrinkage.csv'}")


if __name__ == "__main__":
    main()
