"""
v3 — what a constant round-trip efficiency costs, and what modelling the curve buys back.

Three arms on identical prices and an identical battery:

  reported      optimise with a flat 0.9 efficiency and settle with it too.
                This is the number a conventional model prints.
  actual        take that same schedule and settle it under a load-dependent
                converter model. Same decisions, real physics. The gap to
                `reported` is the error the flat assumption hides.
  aware         optimise with the loss curve inside the linear program, then settle
                under the same physics. The gap to `actual` is what modelling it
                is worth.

The separation matters because the two effects point in opposite directions: the
flat assumption inflates the reported number, while modelling the curve recovers
some of the real revenue by steering the battery away from the low-load region
where efficiency collapses.

Run:  PYTHONPATH=src python3 scripts/v3_converter_efficiency.py 2025-01-01 2025-06-30
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
from bess.degradation.blast_lfp import DegradationCost
from bess.hardware.converter import ConverterModel
from bess.optimise.dispatch import Battery, DispatchConfig, run_backtest, simulate

OUT = Path(__file__).resolve().parents[1] / "results"


def main(start: str, end: str):
    OUT.mkdir(exist_ok=True)
    df = market_index(date.fromisoformat(start), date.fromisoformat(end))
    df = df.dropna(subset=["price"]).reset_index(drop=True)
    prices = df.price.to_numpy(float)

    batt = Battery(power_mw=50, energy_mwh=100)
    conv = ConverterModel(p_rated_mw=batt.power_mw)
    dc = DegradationCost(cell_model="prismatic_250ah", field_annual_loss=0.02)
    c_arb = dc.cost("arbitrage")
    days = len(df) * 0.5 / 24

    s = conv.summary()
    print(f"periods={len(df):,}  days={days:.0f}  c_deg={c_arb:.2f} GBP/MWh")
    print("converter round-trip efficiency by load:",
          {f"{lf:.0%}": rt for lf, rt in zip(s["load_frac"], s["round_trip"])})

    # The converter's no-load loss is real and load-independent; it is applied as a
    # standing draw in every arm so that the optimiser stays linear and the flat and
    # curved arms are compared on the same footing. Thermal management is swept on
    # top of it, because published figures for BESS auxiliary consumption vary widely
    # and no single value should be asserted.
    fixed = conv.fixed_loss_mw
    print(f"converter no-load loss carried as standing draw: {fixed:.2f} MW "
          f"({fixed/batt.power_mw:.1%} of rated)")
    rows = []
    for hvac_mw in (0.0, 0.25, 0.5):
        aux_mw = fixed + hvac_mw
        cfg_flat = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False,
                                  terminal_soc_frac=0.5, aux_standing_mw=aux_mw)
        flat = run_backtest(df, batt, cfg_flat, window_periods=48, execute_periods=48)
        sched = flat["schedule"]

        actual = simulate(sched.charge_mw.to_numpy(), sched.discharge_mw.to_numpy(),
                          prices[:len(sched)], batt, cfg_flat, conv)

        cfg_aware = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False,
                                   terminal_soc_frac=0.5, converter=conv,
                                   aux_standing_mw=aux_mw)
        aware = run_backtest(df, batt, cfg_aware, window_periods=48, execute_periods=48)

        def pmy(x):
            return x / batt.power_mw / days * 365

        overstate = (flat["revenue_net"] / actual["revenue_net"] - 1) * 100
        recover = (aware["revenue_net"] / actual["revenue_net"] - 1) * 100
        rows.append({
            "hvac_MW": hvac_mw, "aux_standing_MW": round(aux_mw, 3),
            "reported_net_GBP": round(flat["revenue_net"]),
            "actual_net_GBP": round(actual["revenue_net"]),
            "aware_net_GBP": round(aware["revenue_net"]),
            "overstatement_pct": round(overstate, 1),
            "recovered_by_modelling_pct": round(recover, 1),
            "reported_GBP_per_MW_yr": round(pmy(flat["revenue_net"])),
            "actual_GBP_per_MW_yr": round(pmy(actual["revenue_net"])),
            "aware_GBP_per_MW_yr": round(pmy(aware["revenue_net"])),
            "delivered_fraction_of_flat_schedule": round(actual["delivered_fraction"], 3),
            "efc_flat": round(flat["efc"] / days * 365, 1),
            "efc_aware": round(aware["efc"] / days * 365, 1),
            "mean_discharge_load_frac_flat": round(
                float(sched.discharge_mw[sched.discharge_mw > 0].mean() / batt.power_mw), 3),
            "mean_discharge_load_frac_aware": round(
                float(aware["schedule"].discharge_mw[aware["schedule"].discharge_mw > 0].mean()
                      / batt.power_mw), 3),
        })
        print(f"  hvac {hvac_mw:4.2f} MW (aux total {aux_mw:4.2f}) | reported {flat['revenue_net']:>9,.0f}"
              f"  actual {actual['revenue_net']:>9,.0f} (overstated {overstate:5.1f}%)"
              f"  aware {aware['revenue_net']:>9,.0f} (recovers {recover:+5.1f}%)")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v3_converter_efficiency.csv", index=False)
    r0 = rows[0]
    summary = {
        "window": [start, end], "battery": "50 MW / 100 MWh (2 h)",
        "converter": {"calibration": "one-way 0.922 at rated, 0.806 at 10 % load "
                                     "(round trip 0.85 / 0.65), after field measurement of a "
                                     "utility-scale BESS, doi:10.1016/j.est.2023.107232",
                      "efficiency_by_load": dict(zip([f"{x:.0%}" for x in s["load_frac"]],
                                                     s["round_trip"]))},
        "finding": (f"a flat 0.9 round-trip efficiency overstates net arbitrage revenue by "
                    f"{r0['overstatement_pct']:.1f} % against the same schedule settled under a "
                    f"load-dependent converter model; putting the loss curve inside the optimiser "
                    f"recovers {r0['recovered_by_modelling_pct']:.1f} % of that, by moving mean "
                    f"discharge load from {r0['mean_discharge_load_frac_flat']:.0%} to "
                    f"{r0['mean_discharge_load_frac_aware']:.0%} of rated power — toward the "
                    f"efficiency peak near half load rather than toward maximum power"),
        "table": rows,
    }
    (OUT / "v3_converter_efficiency.json").write_text(json.dumps(summary, indent=2))
    print(f"\n--- finding ---\n{summary['finding']}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2025-01-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2025-06-30"
    main(a, b)
