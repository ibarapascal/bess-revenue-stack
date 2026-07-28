"""
v1 — the headline experiment: what the SOC-headroom constraint is worth.

A battery paid an availability fee for reserve must actually be able to deliver
that reserve. That requires energy headroom:

    SOC(t) - SOC_min >= R(t) * T_delivery        (to deliver upward)
    SOC_max - SOC(t) >= R(t) * T_delivery        (to absorb downward)

Models that omit this constraint let the same stored energy be sold twice: once
as arbitrage and again as reserve availability. The omission is common because
the model still solves, the schedule still looks sensible, and nothing flags it.

This script measures the overstatement directly by solving the identical problem
with the constraint on and off, and reports the difference as a percentage of
net revenue. The absolute revenue depends on the reserve price assumed, so the
reserve price is swept and the overstatement reported across the sweep — the
result of interest is the structural effect, not one number.

Run:  PYTHONPATH=src python3 scripts/v1_reserve_headroom.py 2025-01-01 2025-03-31
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bess.data.elexon import load_prices
from bess.degradation.blast_lfp import DegradationCost
from bess.optimise.dispatch import Battery, DispatchConfig, run_backtest

OUT = Path(__file__).resolve().parents[1] / "results"


def main(start: str, end: str):
    OUT.mkdir(exist_ok=True)
    df = load_prices(start, end).dropna(subset=["price"]).reset_index(drop=True)

    dc = DegradationCost(cell_model="prismatic_250ah")   # Italian field pair: 1.37 %/yr at 118.7 EFC/yr
    c_arb, c_fr = dc.cost("arbitrage"), dc.cost("frequency")
    print(f"periods={len(df):,}  c_deg arbitrage={c_arb:.2f}  frequency={c_fr:.2f} GBP/MWh")
    print(f"(frequency is cheaper per MWh moved: module tests put peak-shifting ageing at "
          f"{dc.service_multiplier['arbitrage']/dc.service_multiplier['frequency']:.2f}x frequency regulation)")

    batt = Battery(power_mw=50, energy_mwh=100)
    rows = []
    for fr_price in (2.0, 5.0, 10.0, 20.0):
        df2 = df.copy()
        df2["fr_price"] = fr_price                    # stylised flat availability price, GBP/MW/h
        out = {}
        for headroom in (True, False):
            cfg = DispatchConfig(c_deg_arbitrage=c_arb, c_deg_frequency=c_fr,
                                 allow_frequency=True, reserve_headroom=headroom,
                                 )
            r = run_backtest(df2, batt, cfg, fr_col="fr_price",
                             window_periods=96, execute_periods=48)
            out["with" if headroom else "without"] = r
        w, wo = out["with"], out["without"]
        overstate = (wo["revenue_net"] / w["revenue_net"] - 1) * 100 if w["revenue_net"] else np.nan
        res_share_w = w["revenue_fr"] / max(w["revenue_net"], 1e-9) * 100
        rows.append({
            "fr_price_GBP_per_MW_h": fr_price,
            "net_with_headroom": round(w["revenue_net"]),
            "net_without_headroom": round(wo["revenue_net"]),
            "overstatement_pct": round(overstate, 1),
            "fr_share_of_net_pct_with": round(res_share_w, 1),
            "mean_reserve_MW_with": round(float(w["schedule"].reserve_mw.mean()), 2),
            "mean_reserve_MW_without": round(float(wo["schedule"].reserve_mw.mean()), 2),
            "efc_with": round(w["efc"] / w["days"] * 365, 1),
            "efc_without": round(wo["efc"] / wo["days"] * 365, 1),
            "GBP_per_MW_yr_with": round(w["revenue_per_mw_year"]),
            "GBP_per_MW_yr_without": round(wo["revenue_per_mw_year"]),
        })
        print(f"  FR {fr_price:5.1f} GBP/MW/h | net with {w['revenue_net']:>10,.0f}"
              f" vs without {wo['revenue_net']:>10,.0f} -> overstated by {overstate:5.1f}%"
              f" | mean reserve {w['schedule'].reserve_mw.mean():5.1f} vs "
              f"{wo['schedule'].reserve_mw.mean():5.1f} MW")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v1_reserve_headroom.csv", index=False)
    summary = {
        "window": [start, end], "battery": "50 MW / 100 MWh (2 h)",
        "foresight": "perfect (upper bound)",
        "c_deg": {"arbitrage": round(c_arb, 2), "frequency": round(c_fr, 2)},
        "finding": ("omitting the SOC-headroom constraint overstates net revenue by "
                    f"{res.overstatement_pct.min():.1f}-{res.overstatement_pct.max():.1f}% "
                    "across the reserve-price sweep, by selling reserve the battery "
                    "could not have delivered"),
        "table": rows,
    }
    (OUT / "v1_reserve_headroom.json").write_text(json.dumps(summary, indent=2))
    print(f"\n--- finding ---\n{summary['finding']}")
    print(f"written: {OUT/'v1_reserve_headroom.csv'}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2025-01-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2025-03-31"
    main(a, b)
