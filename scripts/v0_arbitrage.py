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
    # A loss rate alone cannot set c_deg: the same annual loss means a very different
    # cost per MWh depending on how much the asset cycled to get there. Only the
    # Italian plant reports both (356 EFC over three years to 95.88 % SoH). The German
    # and EPRI cases give a rate without a cycle count, so they enter as sensitivity
    # under an assumed 300 EFC/yr and are labelled as such rather than as calibration.
    scenarios = [(None, None, "no degradation cost"),
                 (0.0137, 118.7, "Italian field pair, 1.37 %/yr at 119 EFC"),
                 (0.023, 300.0, "EPRI 2.3 %/yr, EFC assumed 300"),
                 (0.03, 300.0, "German upper 3 %/yr, EFC assumed 300")]
    for loss, efc, label in scenarios:
        if loss is None:
            c_deg = 0.0
        else:
            dc = DegradationCost(cell_model="prismatic_250ah", field_annual_loss=loss,
                                 field_efc_per_year=efc)
            c_deg = dc.cost("arbitrage")
        cfg = DispatchConfig(c_deg_arbitrage=c_deg, allow_frequency=False,
                             )
        r = run_backtest(df, batt, cfg, window_periods=96, execute_periods=48)
        rows.append({"scenario": label, "assumed_efc_per_year": efc, "c_deg": round(c_deg, 2),
                     "gross_energy_GBP": round(r["revenue_energy"]),
                     "deg_cost_GBP": round(r["cost_degradation"]),
                     "net_GBP": round(r["revenue_net"]),
                     "efc_per_year": round(r["efc"] / r["days"] * 365, 1),
                     "GBP_per_MW_year": round(r["revenue_per_mw_year"])})
        print(f"  {label:38s} c_deg={c_deg:6.2f}  gross={r['revenue_energy']:>10,.0f}"
              f"  net={r['revenue_net']:>10,.0f}  EFC/yr={r['efc']/r['days']*365:6.1f}"
              f"  {r['revenue_per_mw_year']:>8,.0f} GBP/MW/yr")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v0_arbitrage.csv", index=False)

    base = res.iloc[0]
    summary = {
        "window": [start, end], "battery": "50 MW / 100 MWh (2 h)",
        "note": "perfect foresight — theoretical upper bound, not an achievable revenue",
        # share of *its own* gross margin: dispatch changes with c_deg, so dividing
        # every scenario by the zero-cost scenario's gross would mix bases
        "degradation_cost_share_of_own_gross": {
            r.scenario: round(r.deg_cost_GBP / r.gross_energy_GBP * 100, 1)
            for _, r in res.iloc[1:].iterrows()},
        "efc_reduction_vs_no_cost": {
            r.scenario: round((1 - r.efc_per_year / base.efc_per_year) * 100, 1)
            for _, r in res.iloc[1:].iterrows()},
        "table": rows,
    }
    (OUT / "v0_arbitrage.json").write_text(json.dumps(summary, indent=2))
    print("\n--- what this says ---")
    print("degradation cost as % of own gross arbitrage margin:",
          summary["degradation_cost_share_of_own_gross"])
    print("cycling reduction vs ignoring degradation (% EFC/yr):",
          summary["efc_reduction_vs_no_cost"])
    print(f"\nwritten: {OUT/'v0_arbitrage.csv'}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2025-01-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2025-03-31"
    main(a, b)
