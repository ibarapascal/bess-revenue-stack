"""v5 — separating the efficiency *level* from the efficiency *shape*.

Finding 4 compares a flat 0.9 round trip against a load-dependent curve whose round
trip is 0.937 near rated power, and attributes the whole difference to the curve being
load-dependent. That attribution is not safe: the two arms differ in two ways at once,
and a 2-hour battery discharges at 86 % of rated, which is exactly where the curve is
most generous. Some — possibly all — of what v3 books as "efficiency curve shape" is
the flat assumption simply being set too low.

This separates them. One schedule, three settlements, identical code path, only the
loss model changes:

  flat 0.9025   the conventional assumption (Battery's own 0.95/0.95 one-way)
  flat matched  a *constant* round trip equal to the curve's throughput-weighted
                equivalent on this very schedule — same average efficiency, no shape
  curve         the load-dependent model

    level effect = matched  - flat 0.9025      (same shape, different level)
    shape effect = curve    - matched          (same level, different shape)

The two sum exactly to what v3 reports as the curve term, so this is a decomposition
of that number rather than a competing measurement of it.

Why a fixed schedule makes this exact: with the schedule held, energy revenue is
sum(price * (discharge - charge)), which does not depend on the efficiency model at
all. The only channel through which efficiency can move revenue is *clipping* — an
assumption that stores energy more efficiently fills the battery sooner, so charge
instructions get cut back and less energy is bought. That is a level effect by
construction. Whether any of it survives when the level is equalised is the question.

Run:  PYTHONPATH=src python3 scripts/v5_level_shape.py 2024-03-01 2026-01-01
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


def simulate_flat(schedule_chg, schedule_dis, prices, battery, cfg, eta_round_trip,
                  fixed_loss_mw=0.0):
    """Settle a fixed schedule under a constant round-trip efficiency.

    Deliberately mirrors `dispatch.simulate` line for line — same clipping rule, same
    auxiliary and no-load deductions, same degradation charge — so that the only
    difference between the two settlements is the loss model. A separate code path
    would leave the comparison open to the objection that some other detail moved.

    Losses are symmetric: one-way efficiency is sqrt(round trip) in each direction.
    """
    dt = cfg.dt_hours
    eta = float(np.sqrt(eta_round_trip))
    soc = battery.soc_init
    rev = 0.0
    dis_done = np.zeros_like(schedule_dis)
    chg_done = np.zeros_like(schedule_chg)
    for t in range(len(prices)):
        d, c = float(schedule_dis[t]), float(schedule_chg[t])
        if d > 0:
            avail = max(soc - battery.soc_min, 0.0)
            need = d * dt / eta
            if need > avail:
                d = avail * eta / dt
            soc -= d * dt / eta
        if c > 0:
            room = max(battery.soc_max - soc, 0.0)
            gain = eta * c * dt
            if gain > room:
                c = room / (eta * dt)
            soc += eta * c * dt
        soc = min(max(soc, battery.soc_min), battery.soc_max)
        rev += prices[t] * (d - c) * dt
        if cfg.aux_standing_mw:
            rev -= prices[t] * cfg.aux_standing_mw * dt
        if (d + c) > 1e-6:
            rev -= prices[t] * fixed_loss_mw * dt
        dis_done[t], chg_done[t] = d, c
    deg = cfg.c_deg_arbitrage * float(np.sum(dis_done)) * dt
    return {"revenue_energy": float(rev), "cost_degradation": deg,
            "revenue_net": float(rev - deg),
            "throughput_mwh": float(np.sum(dis_done) * dt),
            "delivered_fraction": float(np.sum(dis_done) / max(np.sum(schedule_dis), 1e-9))}


def matched_round_trip(chg, dis, conv) -> dict:
    """The curve's throughput-weighted equivalent constant round trip on this schedule.

    Defined by energy accounting rather than by averaging the efficiency curve over
    load, because what a flat assumption has to reproduce is the *total* energy into
    and out of storage, not the pointwise efficiency:

        eta_charge    = sum(charge - loss) / sum(charge)
        eta_discharge = sum(discharge) / sum(discharge + loss)

    Averaging eta(P) over operating points instead would weight a half-hour at 5 MW
    the same as a half-hour at 50 MW, which is not the quantity a flat model needs.
    """
    a = conv.k2 / conv.p_rated_mw
    loss_c = a * chg ** 2
    loss_d = a * dis ** 2
    eta_c = float(np.sum(chg - loss_c) / max(np.sum(chg), 1e-9))
    eta_d = float(np.sum(dis) / max(np.sum(dis + loss_d), 1e-9))
    return {"eta_charge": eta_c, "eta_discharge": eta_d, "round_trip": eta_c * eta_d}


def main(start: str, end: str):
    OUT.mkdir(exist_ok=True)
    df = market_index(date.fromisoformat(start),
                      date.fromisoformat(end)).dropna(subset=["price"]).reset_index(drop=True)
    prices = df.price.to_numpy(float)
    days = len(df) * 0.5 / 24

    batt = Battery(power_mw=50, energy_mwh=100)
    conv = ConverterModel(p_rated_mw=batt.power_mw)
    dc = DegradationCost(cell_model="prismatic_250ah")
    c_arb = dc.cost("arbitrage")
    flat_rt = batt.eta_charge * batt.eta_discharge

    print(f"periods={len(df):,}  days={days:.0f}  c_deg={c_arb:.2f} GBP/MWh")
    print(f"conventional flat round trip: {flat_rt:.4f}   curve at rated: "
          f"{float(conv.round_trip(np.array([batt.power_mw]))[0]):.4f}")

    # The schedule every settlement below is applied to: optimised on the flat 0.9
    # assumption, which is what the conventional model would actually dispatch.
    cfg_conv = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False)
    conventional = run_backtest(df, batt, cfg_conv, window_periods=96, execute_periods=48)
    sched = conventional["schedule"]
    chg = sched.charge_mw.to_numpy(float)
    dis = sched.discharge_mw.to_numpy(float)
    p = prices[:len(sched)]

    m = matched_round_trip(chg, dis, conv)
    print(f"\nthroughput-weighted equivalent of the curve on this schedule:")
    print(f"  eta_charge {m['eta_charge']:.4f}  eta_discharge {m['eta_discharge']:.4f}"
          f"  -> round trip {m['round_trip']:.4f}")
    print(f"  against the flat {flat_rt:.4f} the conventional arm assumes"
          f"  (gap {m['round_trip'] - flat_rt:+.4f})")
    print(f"  mean discharge load {float(dis[dis > 0].mean() / batt.power_mw):.1%} of rated")

    rows = []
    for hvac in (0.0, 0.05, 0.10, 0.20):
        cfg_s = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False,
                               aux_standing_mw=hvac)
        # All three use the same clipping rule and the same auxiliary deductions; only
        # the loss model differs. The no-load draw is charged in every arm, including
        # the flat ones, so it cannot leak into the level or shape term.
        a_flat = simulate_flat(chg, dis, p, batt, cfg_s, flat_rt, conv.fixed_loss_mw)
        a_match = simulate_flat(chg, dis, p, batt, cfg_s, m["round_trip"], conv.fixed_loss_mw)
        a_curve = simulate(chg, dis, p, batt, cfg_s, conv)

        level = a_match["revenue_net"] - a_flat["revenue_net"]
        shape = a_curve["revenue_net"] - a_match["revenue_net"]
        total = a_curve["revenue_net"] - a_flat["revenue_net"]
        rows.append({
            "hvac_MW": hvac,
            "flat_0p90_net_GBP": round(a_flat["revenue_net"]),
            "flat_matched_net_GBP": round(a_match["revenue_net"]),
            "curve_net_GBP": round(a_curve["revenue_net"]),
            "level_effect_GBP": round(level),
            "shape_effect_GBP": round(shape),
            "total_GBP": round(total),
            "shape_share_of_total_pct": round(shape / total * 100, 1) if abs(total) > 1 else None,
            "delivered_frac_flat": round(a_flat["delivered_fraction"], 4),
            "delivered_frac_matched": round(a_match["delivered_fraction"], 4),
            "delivered_frac_curve": round(a_curve["delivered_fraction"], 4),
            "throughput_flat_MWh": round(a_flat["throughput_mwh"]),
            "throughput_curve_MWh": round(a_curve["throughput_mwh"]),
        })
        print(f"  hvac {hvac:4.2f} | flat {a_flat['revenue_net']:>10,.0f}"
              f" -> matched {a_match['revenue_net']:>10,.0f} -> curve {a_curve['revenue_net']:>10,.0f}"
              f"  | level {level:>+9,.0f}  shape {shape:>+8,.0f}"
              f"  (shape {shape/total*100 if abs(total) > 1 else float('nan'):5.1f}% of total)")

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v5_level_shape.csv", index=False)

    # ---- the same question, one channel further in -------------------------------
    # v3 also reports that putting the curve *inside* the optimiser is worth 4.2-4.6 %.
    # That comparison has the identical confound: it puts a curve-aware program against
    # one that assumed a flat 0.9025, so the program it beats was mis-levelled as well as
    # shapeless. Splitting it needs a third program optimised on the matched constant,
    # with all three settled the same way — under the curve.
    print("\noptimiser channel: is the curve worth having *inside* the program?")
    cfg_aware = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False, converter=conv)
    aware_curve = run_backtest(df, batt, cfg_aware, window_periods=96, execute_periods=48)

    eta1 = float(np.sqrt(m["round_trip"]))
    batt_matched = Battery(power_mw=batt.power_mw, energy_mwh=batt.energy_mwh,
                           eta_charge=eta1, eta_discharge=eta1)
    cfg_plain = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False)
    aware_matched = run_backtest(df, batt_matched, cfg_plain,
                                 window_periods=96, execute_periods=48)
    sm = aware_matched["schedule"]
    # settled under the curve, exactly as the flat-0.9 schedule was, so the three
    # programs are compared on one settlement basis rather than on their own assumptions
    matched_settled = simulate(sm.charge_mw.to_numpy(float), sm.discharge_mw.to_numpy(float),
                               prices[:len(sm)], batt,
                               DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False), conv)

    base = rows[0]["curve_net_GBP"]          # flat-0.9 program, settled under the curve
    opt_level = matched_settled["revenue_net"] - base
    opt_shape = aware_curve["revenue_net"] - matched_settled["revenue_net"]
    opt_total = aware_curve["revenue_net"] - base
    opt = {
        "flat_0p90_program_settled_on_curve_GBP": round(base),
        "flat_matched_program_settled_on_curve_GBP": round(matched_settled["revenue_net"]),
        "curve_program_GBP": round(aware_curve["revenue_net"]),
        "optimiser_level_effect_GBP": round(opt_level),
        "optimiser_shape_effect_GBP": round(opt_shape),
        "optimiser_total_GBP": round(opt_total),
        "optimiser_total_pct": round(opt_total / base * 100, 1),
        "optimiser_shape_share_pct": round(opt_shape / opt_total * 100, 1) if abs(opt_total) > 1 else None,
        "discharge_load_frac_flat_program": round(float(dis[dis > 0].mean() / batt.power_mw), 3),
        "discharge_load_frac_matched_program": round(
            float(sm.discharge_mw[sm.discharge_mw > 0].mean() / batt.power_mw), 3),
        "discharge_load_frac_curve_program": round(
            float(aware_curve["schedule"].discharge_mw[aware_curve["schedule"].discharge_mw > 0]
                  .mean() / batt.power_mw), 3),
    }
    print(f"  flat 0.9025 program  {base:>10,.0f}")
    print(f"  matched   program  {matched_settled['revenue_net']:>10,.0f}  level {opt_level:>+9,.0f}")
    print(f"  curve     program  {aware_curve['revenue_net']:>10,.0f}  shape {opt_shape:>+9,.0f}")
    print(f"  total {opt_total:+,.0f} ({opt['optimiser_total_pct']:+.1f} %), of which shape "
          f"{opt['optimiser_shape_share_pct']:.1f} %")
    pd.DataFrame([opt]).to_csv(OUT / "v5_optimiser_channel.csv", index=False)

    r0 = rows[0]
    summary = {
        "optimiser_channel": opt,
        "window": [start, end], "battery": "50 MW / 100 MWh (2 h)",
        "flat_round_trip_conventional": round(flat_rt, 4),
        "curve_round_trip_at_rated": round(float(conv.round_trip(np.array([batt.power_mw]))[0]), 4),
        "matched_round_trip": {k: round(v, 4) for k, v in m.items()},
        "mean_discharge_load_frac": round(float(dis[dis > 0].mean() / batt.power_mw), 3),
        "decomposition_note": (
            "one schedule, three settlements, identical clipping and auxiliary treatment. "
            "level = flat-matched minus flat-0.9025; shape = curve minus flat-matched. "
            "With the schedule fixed, energy revenue does not depend on the loss model "
            "except through clipping, so a level difference is the only channel a "
            "constant-efficiency change can act through"),
        "table": rows,
    }
    (OUT / "v5_level_shape.json").write_text(json.dumps(summary, indent=2))
    print(f"\nwritten: {OUT/'v5_level_shape.csv'}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2024-03-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2026-01-01"
    main(a, b)
