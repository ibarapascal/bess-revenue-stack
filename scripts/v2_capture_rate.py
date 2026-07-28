"""
v2 — the number that separates a serious BESS model from a marketing one.

Optimising against realised prices ("perfect foresight") produces a revenue no
operator can earn, because nobody knows tomorrow's prices. The honest figure comes
from optimising against a forecast, executing, and settling against what actually
happened. The ratio of the two is the capture rate.

This script reports:
  1. capture rate for a naive forecaster and for a gradient-boosted one, so the
     revenue gain can be attributed to forecast skill rather than to the mere
     presence of a forecast
  2. the transmission curve: how forecast error translates into revenue, obtained
     by blending forecast and realised prices to sweep skill continuously

Run:  PYTHONPATH=src python3 scripts/v2_capture_rate.py 2024-01-01 2025-12-31
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bess.data.elexon import market_index
from bess.degradation.blast_lfp import DegradationCost
from bess.forecast.price import Forecaster, skill
from bess.optimise.dispatch import Battery, DispatchConfig, run_backtest

OUT = Path(__file__).resolve().parents[1] / "results"


def backtest(df, batt, cfg, forecast_col=None):
    fc = None
    if forecast_col:
        fc = df[["price"]].copy()
        fc["price"] = df[forecast_col].to_numpy()
    return run_backtest(df, batt, cfg, window_periods=96, execute_periods=48, forecast=fc)


def main(start: str, end: str):
    OUT.mkdir(exist_ok=True)
    from datetime import date
    raw = market_index(date.fromisoformat(start), date.fromisoformat(end))
    raw = raw.dropna(subset=["price"]).reset_index(drop=True)
    print(f"raw periods={len(raw):,}  {raw.start_time.min().date()} .. {raw.start_time.max().date()}")

    dc = DegradationCost(cell_model="prismatic_250ah")   # Italian field pair
    c_arb = dc.cost("arbitrage")
    batt = Battery(power_mw=50, energy_mwh=100)
    cfg = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False)

    rows, skills = [], {}
    frames = {}
    for kind in ("persistence", "gbm"):
        f = Forecaster(kind=kind).run(raw)
        frames[kind] = f
        skills[kind] = skill(f)
        print(f"{kind:12s} MAE {skills[kind]['mae']:6.2f}  RMSE {skills[kind]['rmse']:6.2f}"
              f"  dir.acc {skills[kind]['direction_accuracy']:.3f}"
              f"  within-day rank corr {skills[kind]['within_day_rank_corr_median']:.3f}")

    # common evaluation window so every arm sees identical prices
    common = min(len(frames["persistence"]), len(frames["gbm"]))
    base = frames["gbm"].tail(common).reset_index(drop=True)
    pers = frames["persistence"].tail(common).reset_index(drop=True)
    base["fc_persistence"] = pers["forecast"].to_numpy()
    base = base.rename(columns={"forecast": "fc_gbm"})

    perfect = backtest(base, batt, cfg, None)
    print(f"\nperfect foresight   net {perfect['revenue_net']:>12,.0f}  "
          f"{perfect['revenue_per_mw_year']:>7,.0f} GBP/MW/yr  EFC/yr {perfect['efc']/perfect['days']*365:5.1f}")
    rows.append({"arm": "perfect foresight", "mae": 0.0,
                 "gross_GBP": round(perfect["revenue_energy"]),
                 "deg_cost_GBP": round(perfect["cost_degradation"]),
                 "net_GBP": round(perfect["revenue_net"]),
                 "GBP_per_MW_yr": round(perfect["revenue_per_mw_year"]),
                 "capture_gross_pct": 100.0, "capture_net_pct": 100.0,
                 "efc_per_year": round(perfect["efc"] / perfect["days"] * 365, 1)})

    for kind, col in (("persistence", "fc_persistence"), ("gbm", "fc_gbm")):
        r = backtest(base, batt, cfg, col)
        cap = r["revenue_net"] / perfect["revenue_net"] * 100
        cap_g = r["revenue_energy"] / perfect["revenue_energy"] * 100
        mae = float(np.mean(np.abs(base[col] - base["price"])))
        rows.append({"arm": kind, "mae": round(mae, 2),
                     "gross_GBP": round(r["revenue_energy"]),
                     "deg_cost_GBP": round(r["cost_degradation"]),
                     "net_GBP": round(r["revenue_net"]),
                     "GBP_per_MW_yr": round(r["revenue_per_mw_year"]),
                     "capture_gross_pct": round(cap_g, 1), "capture_net_pct": round(cap, 1),
                     "efc_per_year": round(r["efc"] / r["days"] * 365, 1)})
        print(f"{kind:12s} gross {r['revenue_energy']:>11,.0f} ({cap_g:5.1f}%)"
              f"  net {r['revenue_net']:>11,.0f} ({cap:5.1f}%)"
              f"  EFC/yr {r['efc']/r['days']*365:5.1f}")

    # transmission curve: blend forecast toward truth to sweep skill continuously
    print("\nforecast skill -> revenue transmission")
    trans = []
    for w in (0.0, 0.25, 0.5, 0.75, 1.0):
        col = f"_blend_{w}"
        base[col] = (1 - w) * base["fc_gbm"] + w * base["price"]
        r = backtest(base, batt, cfg, col)
        mae = float(np.mean(np.abs(base[col] - base["price"])))
        cap = r["revenue_net"] / perfect["revenue_net"] * 100
        trans.append({"truth_weight": w, "mae": round(mae, 2),
                      "capture_net_pct": round(cap, 1),
                      "capture_gross_pct": round(r["revenue_energy"] / perfect["revenue_energy"] * 100, 1),
                      "net_GBP": round(r["revenue_net"])})
        print(f"  truth weight {w:4.2f}  MAE {mae:6.2f}  capture {cap:5.1f}%")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v2_capture_rate.csv", index=False)
    pd.DataFrame(trans).to_csv(OUT / "v2_transmission.csv", index=False)
    gbm_cap = res.loc[res.arm == "gbm", "capture_net_pct"].iloc[0]
    per_cap = res.loc[res.arm == "persistence", "capture_net_pct"].iloc[0]
    gbm_gross = res.loc[res.arm == "gbm", "capture_gross_pct"].iloc[0]
    summary = {
        "window": [str(base.start_time.min().date()), str(base.start_time.max().date())],
        "battery": "50 MW / 100 MWh (2 h)", "market": "GB wholesale (Elexon MID/APXMIDP)",
        "c_deg_arbitrage": round(c_arb, 2),
        "forecast_skill": skills,
        "capture_net_pct": {"persistence": per_cap, "gbm": gbm_cap},
        "capture_gross_pct_gbm": gbm_gross,
        "finding": (f"forecasting the half-hourly reference price captures {gbm_gross:.0f}% of "
                    f"perfect-foresight gross margin but only {gbm_cap:.0f}% of net revenue: "
                    f"degradation cost is incurred on every cycle whether or not the trade was "
                    f"right, so it amplifies forecast error rather than scaling with it. "
                    f"The naive same-period-yesterday baseline captures {per_cap:.0f}% net."),
        "scope_note": ("This applies to a strategy priced off the half-hourly reference/imbalance "
                       "price, which is not known in advance. It does not apply to day-ahead "
                       "auction arbitrage, where the clearing price is known at gate closure and "
                       "the perfect-foresight figure is close to achievable for that leg. The "
                       "forecast-dependent part of a real revenue stack is within-day and "
                       "balancing, not the day-ahead auction."),
        "arms": rows, "transmission": trans,
    }
    (OUT / "v2_capture_rate.json").write_text(json.dumps(summary, indent=2))
    print(f"\n--- finding ---\n{summary['finding']}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2024-01-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2025-12-31"
    main(a, b)
