"""v6 — does any of finding 4 survive at a different duration?

The README states finding 4 "holds for a 2-hour asset discharging at 86 % of rated" and
that "a longer-duration asset may flip it", then never tests it. The mechanism it appeals
to is real: a longer asset spreads the same energy over more hours, discharges at a lower
fraction of rated power, and so sits further down the efficiency curve where the flat
assumption is less obviously too generous.

Three durations at fixed power, so the only thing changing is how long the asset can run:

    1 h   50 MW /  50 MWh
    2 h   50 MW / 100 MWh   (the asset every other result uses)
    4 h   50 MW / 200 MWh

Reported per duration:
  - mean discharge load, the variable the flip is supposed to hinge on
  - the v5 level/shape split, to see whether the shape term is small everywhere or only
    at 2 hours
  - the v3 overstatement, on v3's own definition, to see whether the sign flips
  - what pricing degradation costs, as a check that the v0 finding is not duration-bound

Run:  PYTHONPATH=src python3 scripts/v6_duration.py 2024-03-01 2026-01-01
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v5_level_shape import matched_round_trip, simulate_flat  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "results"

DURATIONS = [(1.0, 50.0), (2.0, 100.0), (4.0, 200.0)]


def main(start: str, end: str):
    OUT.mkdir(exist_ok=True)
    df = market_index(date.fromisoformat(start),
                      date.fromisoformat(end)).dropna(subset=["price"]).reset_index(drop=True)
    prices = df.price.to_numpy(float)
    days = len(df) * 0.5 / 24
    dc = DegradationCost(cell_model="prismatic_250ah")
    c_arb = dc.cost("arbitrage")
    print(f"periods={len(df):,}  days={days:.0f}  c_deg={c_arb:.2f} GBP/MWh")

    rows = []
    for hours, mwh in DURATIONS:
        batt = Battery(power_mw=50.0, energy_mwh=mwh)
        conv = ConverterModel(p_rated_mw=batt.power_mw)
        flat_rt = batt.eta_charge * batt.eta_discharge

        # 1. what a conventional model dispatches and prints
        cfg_conv = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False)
        conventional = run_backtest(df, batt, cfg_conv, window_periods=96, execute_periods=48)
        sched = conventional["schedule"]
        chg = sched.charge_mw.to_numpy(float)
        dis = sched.discharge_mw.to_numpy(float)
        p = prices[:len(sched)]
        load_frac = float(dis[dis > 0].mean() / batt.power_mw)

        # 2. level / shape split on that schedule, no thermal load (the headline case)
        m = matched_round_trip(chg, dis, conv)
        cfg_s = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False)
        a_flat = simulate_flat(chg, dis, p, batt, cfg_s, flat_rt, conv.fixed_loss_mw)
        a_match = simulate_flat(chg, dis, p, batt, cfg_s, m["round_trip"], conv.fixed_loss_mw)
        a_curve = simulate(chg, dis, p, batt, cfg_s, conv)
        level = a_match["revenue_net"] - a_flat["revenue_net"]
        shape = a_curve["revenue_net"] - a_match["revenue_net"]
        total = a_curve["revenue_net"] - a_flat["revenue_net"]

        # 3. v3's overstatement, on v3's definition: the conventional print, which pays
        #    no auxiliaries at all, against the same schedule settled under the curve
        overstate = (conventional["revenue_net"] / a_curve["revenue_net"] - 1) * 100

        # 4. curve inside the optimiser
        cfg_aware = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False,
                                   converter=conv)
        aware = run_backtest(df, batt, cfg_aware, window_periods=96, execute_periods=48)
        recovered = (aware["revenue_net"] / a_curve["revenue_net"] - 1) * 100
        aware_load = float(aware["schedule"].discharge_mw[aware["schedule"].discharge_mw > 0]
                           .mean() / batt.power_mw)

        # 5. is the degradation finding duration-bound?
        cfg_free = DispatchConfig(c_deg_arbitrage=0.0, allow_frequency=False)
        free = run_backtest(df, batt, cfg_free, window_periods=96, execute_periods=48)
        deg_overstate = (free["revenue_net"] / conventional["revenue_net"] - 1) * 100

        rows.append({
            "duration_h": hours, "energy_mwh": mwh,
            "mean_discharge_load_frac": round(load_frac, 3),
            "matched_round_trip": round(m["round_trip"], 4),
            "flat_round_trip": round(flat_rt, 4),
            "level_effect_GBP": round(level),
            "shape_effect_GBP": round(shape),
            "total_curve_term_GBP": round(total),
            "shape_share_of_total_pct": round(shape / total * 100, 1) if abs(total) > 1 else None,
            "conventional_net_GBP": round(conventional["revenue_net"]),
            "curve_net_GBP": round(a_curve["revenue_net"]),
            "overstatement_pct_no_thermal": round(overstate, 1),
            "aware_net_GBP": round(aware["revenue_net"]),
            "recovered_by_modelling_pct": round(recovered, 1),
            "aware_discharge_load_frac": round(aware_load, 3),
            "efc_per_year_conventional": round(conventional["efc"] / days * 365, 1),
            "efc_per_year_no_deg_cost": round(free["efc"] / days * 365, 1),
            "no_deg_net_GBP": round(free["revenue_net"]),
            "deg_overstatement_pct": round(deg_overstate, 1),
            "GBP_per_MW_yr_conventional": round(conventional["revenue_per_mw_year"]),
        })
        print(f"  {hours:.0f} h | load {load_frac:5.1%}  matched RT {m['round_trip']:.4f}"
              f" | level {level:>+9,.0f}  shape {shape:>+8,.0f}"
              f" ({shape/total*100 if abs(total) > 1 else float('nan'):5.1f}%)"
              f" | overstate {overstate:>+5.1f}%  aware {recovered:>+4.1f}%"
              f" | deg overstate {deg_overstate:>5.1f}%")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v6_duration.csv", index=False)

    shares = [r["shape_share_of_total_pct"] for r in rows if r["shape_share_of_total_pct"] is not None]
    signs = {r["duration_h"]: r["overstatement_pct_no_thermal"] for r in rows}
    summary = {
        "window": [start, end], "power_mw": 50.0,
        "durations_h": [d for d, _ in DURATIONS],
        "finding": (
            f"across 1, 2 and 4 hours the shape term stays between "
            f"{min(shares):.1f} % and {max(shares):.1f} % of what v3 books as the "
            f"efficiency-curve error, so the level/shape confound is not an artefact of "
            f"the 2-hour asset. The no-thermal overstatement is "
            + ", ".join(f"{k:.0f} h {v:+.1f} %" for k, v in signs.items())
            + (" — it does not change sign over this range"
               if len({v > 0 for v in signs.values()}) == 1 else
               " — it does change sign over this range")),
        "note": ("mean discharge load is the variable the README expects the flip to hinge "
                 "on; it is reported per duration so the mechanism can be checked directly "
                 "rather than assumed"),
        "table": rows,
    }
    (OUT / "v6_duration.json").write_text(json.dumps(summary, indent=2))
    print(f"\n--- finding ---\n{summary['finding']}")
    print(f"\nwritten: {OUT/'v6_duration.csv'}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2024-03-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2026-01-01"
    main(a, b)
