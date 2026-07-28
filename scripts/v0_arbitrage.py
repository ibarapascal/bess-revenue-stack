"""
v0 — energy arbitrage only, perfect foresight, field-anchored degradation cost.

Purpose is not the revenue number itself (perfect foresight is an upper bound and
is never achievable). It is to establish the pipeline and to produce the first two
quantified results:

  1. how much of gross arbitrage margin degradation cost consumes, across the
     1.4-3 %/yr field range of system degradation
  2. how sensitive dispatch is to c_deg at all — i.e. whether treating it as a
     constant, as most public models do, is a benign simplification

Run:  PYTHONPATH=src python3 scripts/v0_arbitrage.py 2025-01-01 2025-12-31
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bess.data.elexon import load_prices
from bess.degradation.blast_lfp import DegradationCost
from bess.optimise.dispatch import Battery, DispatchConfig, run_backtest

OUT = Path(__file__).resolve().parents[1] / "results"


def main(start: str, end: str):
    OUT.mkdir(exist_ok=True)
    df = load_prices(start, end).dropna(subset=["price"]).reset_index(drop=True)
    print(f"periods={len(df):,}  {df.start_time.min()} .. {df.start_time.max()}")
    print(f"price GBP/MWh: mean {df.price.mean():.1f}  p5 {df.price.quantile(.05):.1f}"
          f"  p95 {df.price.quantile(.95):.1f}  negative periods {(df.price < 0).mean():.1%}")

    batt = Battery(power_mw=50, energy_mwh=100)
    rows = []
    for loss in (None, 0.014, 0.02, 0.03):
        if loss is None:
            c_deg, label = 0.0, "no degradation cost"
        else:
            dc = DegradationCost(cell_model="prismatic_250ah", field_annual_loss=loss)
            c_deg, label = dc.cost("arbitrage"), f"{loss:.1%}/yr field-anchored"
        cfg = DispatchConfig(c_deg_arbitrage=c_deg, allow_frequency=False,
                             terminal_soc_frac=0.5)
        r = run_backtest(df, batt, cfg, window_periods=48, execute_periods=48)
        rows.append({"scenario": label, "c_deg": round(c_deg, 2),
                     "gross_energy_GBP": round(r["revenue_energy"]),
                     "deg_cost_GBP": round(r["cost_degradation"]),
                     "net_GBP": round(r["revenue_net"]),
                     "efc_per_year": round(r["efc"] / r["days"] * 365, 1),
                     "GBP_per_MW_year": round(r["revenue_per_mw_year"])})
        print(f"  {label:26s} c_deg={c_deg:6.2f}  gross={r['revenue_energy']:>10,.0f}"
              f"  net={r['revenue_net']:>10,.0f}  EFC/yr={r['efc']/r['days']*365:6.1f}"
              f"  {r['revenue_per_mw_year']:>8,.0f} GBP/MW/yr")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v0_arbitrage.csv", index=False)

    base = res.iloc[0]
    summary = {
        "window": [start, end], "battery": "50 MW / 100 MWh (2 h)",
        "note": "perfect foresight — theoretical upper bound, not an achievable revenue",
        "degradation_cost_share_of_gross": {
            r.scenario: round(r.deg_cost_GBP / base.gross_energy_GBP * 100, 1)
            for _, r in res.iloc[1:].iterrows()},
        "efc_reduction_vs_no_cost": {
            r.scenario: round((1 - r.efc_per_year / base.efc_per_year) * 100, 1)
            for _, r in res.iloc[1:].iterrows()},
        "table": rows,
    }
    (OUT / "v0_arbitrage.json").write_text(json.dumps(summary, indent=2))
    print("\n--- what this says ---")
    print("degradation cost as % of gross arbitrage margin:",
          summary["degradation_cost_share_of_gross"])
    print("cycling reduction vs ignoring degradation (% EFC/yr):",
          summary["efc_reduction_vs_no_cost"])
    print(f"\nwritten: {OUT/'v0_arbitrage.csv'}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2025-01-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2025-03-31"
    main(a, b)
