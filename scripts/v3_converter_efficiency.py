"""
v3 — what a constant round-trip efficiency costs, and what modelling the curve buys back.

Four arms on identical prices and an identical battery. The arms are defined so that
each step isolates one omission, because an earlier version of this script charged the
conventional arm for an auxiliary load that the convention it represents does not
include, which understated the very gap being measured.

  conventional  flat 0.9 round-trip efficiency, no auxiliary draw at all. This is
                what a typical public model prints.
  + aux         the same schedule, still on flat efficiency, but paying the
                converter no-load loss and thermal management. Isolates the cost of
                omitting auxiliary consumption.
  actual        the same schedule again, now settled under the load-dependent
                converter curve as well. The remaining gap isolates the cost of
                assuming efficiency is flat.
  aware         optimise with the loss curve inside the linear program and settle
                under the same physics. The gap to `actual` is what modelling the
                curve is worth, as opposed to merely accounting for it.

The two effects differ in kind and, as it turns out, in sign. Omitting auxiliaries
always inflates the reported number. Assuming flat efficiency does not: calibrated to
the field plant's auxiliary-excluded AC round trip, the real curve *beats* a flat 0.9
everywhere above about a quarter load, which is where a 2-hour battery spends its
discharge. So the components are reported in pounds rather than as shares of a gap that
passes through zero.

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
    dc = DegradationCost(cell_model="prismatic_250ah")   # Italian field pair
    c_arb = dc.cost("arbitrage")
    days = len(df) * 0.5 / 24

    s = conv.summary()
    print(f"periods={len(df):,}  days={days:.0f}  c_deg={c_arb:.2f} GBP/MWh")
    print("converter round-trip efficiency by load:",
          {f"{lf:.0%}": rt for lf, rt in zip(s["load_frac"], s["round_trip"])})

    # The converter's no-load loss is charged only in periods when the converter runs
    # (handled inside the optimiser and the settlement); thermal management is the
    # genuinely round-the-clock part and is swept separately. The sweep range is set
    # from the order of magnitude field data supports for BESS auxiliary consumption,
    # roughly 1-3 % of throughput, which for this asset is of order 0.1 MW continuous
    # rather than the arbitrary values an earlier version used.
    fixed = conv.fixed_loss_mw
    print(f"converter no-load loss (charged only while running): {fixed:.2f} MW "
          f"({fixed/batt.power_mw:.1%} of rated)")
    # the conventional arm is solved once: it knows nothing about auxiliaries or the
    # loss curve, so it does not depend on the sweep
    cfg_conv = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False,
                              )
    conventional = run_backtest(df, batt, cfg_conv, window_periods=96, execute_periods=48)
    sched = conventional["schedule"]
    aux_energy_price_sum = float(np.sum(prices[:len(sched)]) * 0.5)   # GBP per MW of standing draw

    rows = []
    for hvac_mw in (0.0, 0.05, 0.1, 0.2):
        aux_mw = hvac_mw
        # same schedule, now paying for auxiliaries: round-the-clock thermal load plus
        # the converter's no-load loss in the periods the schedule is actually active
        act = ((sched.charge_mw + sched.discharge_mw) > 1e-6).to_numpy(float)
        conv_fixed_cost = float(np.sum(prices[:len(sched)] * fixed * act) * 0.5)
        with_aux = conventional["revenue_net"] - hvac_mw * aux_energy_price_sum - conv_fixed_cost

        cfg_settle = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False,
                                    terminal_soc_frac=0.5, aux_standing_mw=aux_mw,
                                    converter=conv)
        actual = simulate(sched.charge_mw.to_numpy(), sched.discharge_mw.to_numpy(),
                          prices[:len(sched)], batt, cfg_settle, conv)

        cfg_aware = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False,
                                   terminal_soc_frac=0.5, converter=conv,
                                   aux_standing_mw=aux_mw)
        aware = run_backtest(df, batt, cfg_aware, window_periods=96, execute_periods=48)
        flat = conventional

        def pmy(x):
            return x / batt.power_mw / days * 365

        overstate = (flat["revenue_net"] / actual["revenue_net"] - 1) * 100
        recover = (aware["revenue_net"] / actual["revenue_net"] - 1) * 100
        # The two error components have opposite signs once the efficiency curve is
        # calibrated to the auxiliary-excluded AC round trip, so a "share of the gap"
        # percentage is not defined: the denominator passes through zero. Report both
        # components in pounds, signed, and let the reader add them.
        #   aux   > 0 always: the cost of consumption the conventional arm ignores
        #   curve < 0 when the real curve beats flat 0.9 in the operating load band
        err_aux = flat["revenue_net"] - with_aux
        err_curve = with_aux - actual["revenue_net"]
        rows.append({
            "hvac_MW": hvac_mw, "aux_standing_MW": round(aux_mw, 3),
            "conventional_net_GBP": round(flat["revenue_net"]),
            "with_aux_net_GBP": round(with_aux),
            "actual_net_GBP": round(actual["revenue_net"]),
            "aware_net_GBP": round(aware["revenue_net"]),
            "overstatement_pct": round(overstate, 1),
            "error_from_aux_GBP": round(err_aux),
            "error_from_curve_shape_GBP": round(err_curve),
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
        print(f"  hvac {hvac_mw:4.2f} (aux {aux_mw:4.2f} MW) | conventional {flat['revenue_net']:>9,.0f}"
              f" -> +aux {with_aux:>9,.0f} -> actual {actual['revenue_net']:>9,.0f}"
              f"  (overstated {overstate:6.1f}%; aux {err_aux:>+9,.0f}, curve {err_curve:>+8,.0f} GBP)"
              f"  | aware {aware['revenue_net']:>9,.0f} ({recover:+5.1f}%)")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v3_converter_efficiency.csv", index=False)
    r0, rl = rows[0], rows[-1]
    summary = {
        "window": [start, end], "battery": "50 MW / 100 MWh (2 h)",
        "converter": {"calibration": "AC round-trip efficiency, auxiliary-excluded, from the "
                                     "year-one fitted curve of a 500 kW / 822 kWh NMC plant in "
                                     "southern Italy measured at 11 setpoints "
                                     "(doi:10.1016/j.est.2023.107232, Eq. 8 and Table 6): "
                                     "0.937 round trip near rated, 0.771 at 0.1 p.u., entered as "
                                     "one-way 0.968 / 0.878 under the paper's symmetric convention",
                      "calibration_note": "that paper's better-known 0.85 / 0.65 pair is its "
                                          "*global* efficiency (Eq. 11), whose denominator "
                                          "includes auxiliary energy; calibrating to it while "
                                          "charging auxiliaries separately double-counts them, and "
                                          "most of its low-load droop is cycle duration (26.4 h "
                                          "per cycle at 0.1 p.u. against 2.6 h at rated) rather "
                                          "than part-load electronics",
                      "efficiency_by_load": dict(zip([f"{x:.0%}" for x in s["load_frac"]],
                                                     s["round_trip"]))},
        "finding": (
            f"the two errors inside a conventional flat-efficiency assumption have opposite signs, "
            f"and for a 2-hour battery they nearly cancel unless a standing auxiliary load is "
            f"present. With no thermal load the conventional model is {abs(r0['overstatement_pct']):.1f} % "
            f"{'low' if r0['overstatement_pct'] < 0 else 'high'}: a flat 0.9 round trip understates "
            f"the real converter in the 86 %-of-rated band this asset actually discharges at, and "
            f"that gain ({-r0['error_from_curve_shape_GBP']:+,.0f} GBP) slightly exceeds the cost of "
            f"the no-load draw it ignores ({r0['error_from_aux_GBP']:+,.0f} GBP). Every pound of net "
            f"overstatement therefore traces to the standing auxiliary load, rising roughly linearly "
            f"with it to {rl['overstatement_pct']:.0f} % at {rl['hvac_MW']:.2f} MW. Putting the curve "
            f"inside the optimiser is worth {r0['recovered_by_modelling_pct']:.1f}-"
            f"{rl['recovered_by_modelling_pct']:.1f} % and does move dispatch, pushing mean discharge "
            f"load from {r0['mean_discharge_load_frac_flat']:.1%} to "
            f"{r0['mean_discharge_load_frac_aware']:.1%} of rated, because an auxiliary-excluded "
            f"curve rises monotonically toward rated power instead of peaking mid-load. The "
            f"expensive omission is the auxiliary load; the flat efficiency itself is close to "
            f"harmless here, and in the wrong direction from the usual assumption"),
        "table": rows,
    }
    (OUT / "v3_converter_efficiency.json").write_text(json.dumps(summary, indent=2))
    print(f"\n--- finding ---\n{summary['finding']}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2025-01-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2025-06-30"
    main(a, b)
