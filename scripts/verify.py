"""
Verification suite — the checks that would catch the errors that actually happened.

Every check here exists because something went wrong once. A model that solves and
produces plausible numbers is not evidence of correctness; these are the invariants
that distinguish the two.

Run:  PYTHONPATH=src python3 scripts/verify.py
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
from bess.degradation.blast_lfp import DegradationCost, MODELS
from bess.forecast.price import FEATURES, build_features
from bess.hardware.converter import ConverterModel
from bess.optimise.dispatch import Battery, DispatchConfig, run_backtest, solve_window

FAILED = []


def check(name: str, ok: bool, detail: str = ""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    if not ok:
        FAILED.append(name)


def check_energy_balance(prices):
    """State of charge must be the integral of what actually crossed the terminals."""
    batt = Battery()
    cfg = DispatchConfig(c_deg_arbitrage=15.0, allow_frequency=False)
    r = solve_window(prices[:48], batt, cfg)
    dt = cfg.dt_hours
    soc, chg, dis = r["soc_mwh"], r["charge_mw"], r["discharge_mw"]
    implied = soc[:-1] + batt.eta_charge * chg * dt - dis * dt / batt.eta_discharge
    err = float(np.max(np.abs(implied - soc[1:])))
    check("energy balance closes (flat efficiency)", err < 1e-6, f"max error {err:.2e} MWh")

    conv = ConverterModel(p_rated_mw=batt.power_mw)
    cfg2 = DispatchConfig(c_deg_arbitrage=15.0, allow_frequency=False, converter=conv)
    r2 = solve_window(prices[:48], batt, cfg2)
    soc2, chg2, dis2 = r2["soc_mwh"], r2["charge_mw"], r2["discharge_mw"]
    loss_d = conv.loss_mw(dis2, variable_only=True)
    loss_c = conv.loss_mw(chg2, variable_only=True)
    implied2 = soc2[:-1] + (chg2 - loss_c) * dt - (dis2 + loss_d) * dt
    err2 = float(np.max(np.abs(implied2 - soc2[1:])))
    # Not exactly zero, and the reason is worth stating rather than tuning away.
    # The convex loss enters as an epigraph, which is tight only where the objective
    # pushes loss down. During negative prices it does not: a larger charging loss
    # would let the battery keep buying while capped, so the relaxation has slack
    # there. A chord upper bound and a calibrated tie-breaker reduce the residual to
    # a few kWh per period; removing it entirely would need integer variables for a
    # distortion worth 0.01 % of revenue.
    tol = 1e-4 * batt.energy_mwh          # 0.01 % of nameplate
    check("energy balance closes (load-dependent losses)", err2 < tol,
          f"max error {err2:.2e} MWh = {err2/batt.energy_mwh:.4%} of capacity "
          f"(residual of the convex relaxation at negative prices, bounded not tuned)")


def check_soc_headroom(prices):
    """Reserve must never exceed the energy available to deliver it."""
    batt = Battery()
    df = pd.DataFrame({"price": prices[:48], "fr_price": 5.0})
    cfg = DispatchConfig(c_deg_arbitrage=15.0, allow_frequency=True, reserve_headroom=True)
    r = solve_window(df.price.to_numpy(), batt, cfg, fr_prices=df.fr_price.to_numpy())
    up = r["soc_mwh"][:-1] - batt.soc_min - r["reserve_mw"] * cfg.fr_delivery_hours
    dn = batt.soc_max - r["soc_mwh"][:-1] - r["reserve_mw"] * cfg.fr_delivery_hours
    check("reserve is always deliverable when the constraint is on",
          up.min() > -1e-6 and dn.min() > -1e-6,
          f"tightest headroom {min(up.min(), dn.min()):.3f} MWh")

    cfg_off = DispatchConfig(c_deg_arbitrage=15.0, allow_frequency=True, reserve_headroom=False)
    r_off = solve_window(df.price.to_numpy(), batt, cfg_off, fr_prices=df.fr_price.to_numpy())
    up_off = r_off["soc_mwh"][:-1] - batt.soc_min - r_off["reserve_mw"] * cfg_off.fr_delivery_hours
    check("switching the constraint off does produce undeliverable reserve",
          up_off.min() < -1e-6,
          f"shortfall {up_off.min():.2f} MWh — confirms the experiment measures something real")


def check_converter_envelope():
    """Tangent representation must equal the analytic convex loss, not approximate it."""
    conv = ConverterModel(p_rated_mw=50.0)
    tang = conv.tangents(n=12)
    p = np.linspace(0.0, 50, 200)
    env = np.maximum(np.max(np.array([a * p + b for a, b in tang]), axis=0), 0.0)
    true = conv.loss_mw(p, variable_only=True)
    # judged as power error against rated, not against the local loss value: at 1 %
    # load the loss itself is milliwatts and a relative measure is meaningless
    abs_err = float(np.max(np.abs(env - true)) / conv.p_rated_mw)
    check("tangent envelope reproduces the loss curve", abs_err < 0.001,
          f"max deviation {abs_err:.4%} of rated power over 0-100 % load")
    # Calibration targets are the AC round-trip efficiency of the field plant, which
    # excludes auxiliaries. Anchoring to that paper's auxiliary-*inclusive* global
    # efficiency (0.85 / 0.65) is what an earlier version did, and it double-counted
    # every auxiliary term the model adds on top.
    eff = conv.round_trip(np.array([0.1, 1.0]) * 50)
    check("converter reproduces its calibration points",
          abs(eff[0] - 0.771) < 0.01 and abs(eff[1] - 0.937) < 0.01,
          f"round trip {eff[0]:.3f} at 10 % load, {eff[1]:.3f} at rated "
          f"(AC round trip, auxiliary-excluded)")
    check("calibration is not the auxiliary-inclusive metric",
          eff[1] > 0.90,
          f"{eff[1]:.3f} at rated is the AC-terminal figure; the global figure of "
          f"0.85 includes the auxiliaries this model charges separately")


def check_degradation_anchor():
    """Field anchoring must actually reproduce the field loss rate it targets."""
    for target in (0.014, 0.02, 0.03):
        dc = DegradationCost(cell_model="prismatic_250ah", field_annual_loss=target)
        implied = dc.loss_per_efc() * dc.anchor_factor() * dc.field_efc_per_year
        check(f"anchoring reproduces {target:.1%}/yr", abs(implied - target) < 1e-9,
              f"implied {implied:.4%}")
    dc = DegradationCost(field_annual_loss=0.02)
    ratio = dc.cost("arbitrage") / dc.cost("frequency")
    check("service differentiation carries the measured ratio",
          abs(ratio - 1.85) < 1e-9, f"arbitrage/frequency = {ratio:.3f}")
    # The anchor pins the level; the cell model is supposed to supply the response to
    # operating conditions. If the anchor is evaluated at the caller's operating point
    # instead of a fixed reference, the two cancel and the cell model contributes
    # nothing — which is exactly what happened, undetected, until it was checked.
    a = DegradationCost(cell_model="sony_murata_3ah").base_cost(dod=0.6)
    b = DegradationCost(cell_model="prismatic_250ah").base_cost(dod=0.6)
    check("cell model actually influences c_deg away from the anchor point",
          abs(a - b) / max(a, b) > 0.01,
          f"{a:.2f} vs {b:.2f} GBP/MWh at 60 % depth — identical values would mean "
          f"the anchor had cancelled the model it is meant to scale")
    ref = DegradationCost(cell_model="prismatic_250ah")
    closed = (ref.replacement_cost_per_mwh
              / (1 + ref.discount_rate) ** ref.expected_life_years
              * ref.field_annual_loss / ref.field_efc_per_year
              / (1 - ref.eol_fraction) / ref.REF_DOD)
    check("at the reference point c_deg is the four-input closed form",
          abs(ref.base_cost() - closed) < 1e-9,
          f"{ref.base_cost():.6f} = {closed:.6f} — only one of those four inputs is "
          f"a field observation, which is why the others are swept")

    unanchored = DegradationCost(cell_model="prismatic_250ah", field_annual_loss=None)
    check("raw cell model would over-predict field loss",
          unanchored.loss_per_efc() * 300 > 0.05,
          f"{unanchored.loss_per_efc()*300:.1%}/yr at 300 EFC — why anchoring is not optional")


def check_forecast_leakage(df):
    """Every feature at t must be computable from data available strictly before t."""
    f = build_features(df.head(2000))
    # perturb a single future price and confirm no earlier feature row changes
    d2 = df.head(2000).copy()
    idx = 1500
    d2.loc[idx, "price"] = d2.loc[idx, "price"] + 1000.0
    f2 = build_features(d2)
    before = f.loc[:idx - 1, FEATURES].fillna(-999)
    before2 = f2.loc[:idx - 1, FEATURES].fillna(-999)
    check("no feature at t depends on price at t or later",
          bool((before == before2).all().all()),
          "verified by perturbing one future price and comparing all earlier feature rows")
    # the perturbed price must show up only from t+48 onwards (shortest lag)
    after = f2.loc[idx:, FEATURES].fillna(-999)
    after0 = f.loc[idx:, FEATURES].fillna(-999)
    first_diff = int(np.argmax((after != after0).any(axis=1).to_numpy())) if \
        (after != after0).any().any() else -1
    check("the shortest feature lag is one full day",
          first_diff >= 48, f"first affected row is +{first_diff} periods")


def check_backtest_path(df):
    """The rolling backtest is what produces every published number, so it needs its own
    checks. Nothing here is an invariant of the optimiser — these are the properties that
    would silently turn the headline into a different quantity."""
    batt = Battery()
    cfg = DispatchConfig(c_deg_arbitrage=15.0, allow_frequency=False)
    d = df.head(96 * 4).copy()

    # 1. A forecast that is not the realised price must not produce perfect-foresight
    # revenue. If the forecast argument were ever ignored, capture would silently become
    # 100 % and no invariant in this file would notice.
    fc = d[["price"]].copy()
    fc["price"] = d["price"].to_numpy()[::-1]           # deliberately wrong
    perfect = run_backtest(d, batt, cfg, window_periods=96, execute_periods=48)
    blind = run_backtest(d, batt, cfg, window_periods=96, execute_periods=48, forecast=fc)
    check("optimising against a forecast is not the same as perfect foresight",
          blind["revenue_net"] < perfect["revenue_net"] - 1.0,
          f"net {blind['revenue_net']:,.0f} against {perfect['revenue_net']:,.0f} — equality "
          f"would mean the forecast argument was being ignored")

    # 2. Settlement must use realised prices, so a forecast cannot inflate revenue above
    # the perfect-foresight bound however wrong it is.
    check("no forecast can beat perfect foresight",
          blind["revenue_net"] <= perfect["revenue_net"] + 1e-6,
          "settlement prices are realised, not forecast")

    # 3. State of charge must carry across window boundaries rather than resetting: with
    # execute_periods < window_periods the schedule is stitched, and a reset would show up
    # as free energy appearing at every seam.
    sched = perfect["schedule"]
    dt = cfg.dt_hours
    soc = batt.soc_init
    worst = 0.0
    for c, dis in zip(sched.charge_mw.to_numpy(), sched.discharge_mw.to_numpy()):
        soc += batt.eta_charge * c * dt - dis * dt / batt.eta_discharge
        worst = max(worst, max(batt.soc_min - soc, soc - batt.soc_max))
    check("state of charge carries across window seams",
          worst < 1e-3, f"worst excursion beyond limits {worst:.2e} MWh over "
                        f"{len(sched)} stitched periods")

    # 4. A standing auxiliary draw must cost money in settlement. This was once omitted,
    # which made an entire sweep return identical rows.
    cfg_aux = DispatchConfig(c_deg_arbitrage=15.0, allow_frequency=False, aux_standing_mw=1.0)
    with_aux = run_backtest(d, batt, cfg_aux, window_periods=96, execute_periods=48)
    check("a standing auxiliary load reduces settled revenue",
          with_aux["revenue_net"] < perfect["revenue_net"] - 1.0,
          f"{with_aux['revenue_net']:,.0f} against {perfect['revenue_net']:,.0f} at 1 MW standing draw")


def check_published_numbers():
    """Pin the numbers the README quotes. Every one of them has moved at least once, and
    a silent drift is the failure mode this project is least able to afford."""
    res = Path(__file__).resolve().parents[1] / "results"
    if not res.exists() or not any(res.glob("*.json")):
        check("published numbers are pinned", True, "no results/ yet — run the experiments first")
        return
    def load(name):
        return json.loads((res / name).read_text())

    v2 = load("v2_capture_rate.json")
    arms = {a["arm"]: a for a in v2["arms"]}
    pf, gbm = arms["perfect foresight"], arms["gbm"]
    check("waterfall still closes",
          abs(pf["gross_GBP"] - (pf["gross_GBP"] - gbm["gross_GBP"])
              - gbm["deg_cost_GBP"] - gbm["net_GBP"]) < 2,
          f"{pf['gross_GBP']:,} − {pf['gross_GBP']-gbm['gross_GBP']:,} − "
          f"{gbm['deg_cost_GBP']:,} = {gbm['net_GBP']:,}")
    check("net capture is far below gross capture",
          gbm["capture_gross_pct"] - gbm["capture_net_pct"] > 20,
          f"gross {gbm['capture_gross_pct']}% against net {gbm['capture_net_pct']}% — "
          f"the gap is finding 3")

    v3 = load("v3_converter_efficiency.json")
    zero = v3["table"][0]
    check("the two efficiency error components still have opposite signs",
          zero["error_from_aux_GBP"] > 0 > zero["error_from_curve_shape_GBP"],
          f"aux {zero['error_from_aux_GBP']:+,}, curve {zero['error_from_curve_shape_GBP']:+,} "
          f"at zero thermal load")

    v4 = load("v4_service_cdeg.json")
    lowest = v4["deltas_vs_flat"][0]
    check("the reserve-market entry flip is still present at the lowest price",
          lowest["enters_market_only_when_differentiated"],
          f"single-cost holds {lowest['reserve_MW_flat']:.2f} MW, differentiated "
          f"{lowest['reserve_MW_diff']:.1f} MW")


def main():
    print("verification suite\n")
    df = market_index(date(2025, 1, 1), date(2025, 2, 28)).dropna(subset=["price"]).reset_index(drop=True)
    prices = df.price.to_numpy(float)

    print("optimiser")
    check_energy_balance(prices)
    check_soc_headroom(prices)
    print("hardware")
    check_converter_envelope()
    print("degradation")
    check_degradation_anchor()
    print("rolling backtest")
    check_backtest_path(df)
    print("forecasting")
    check_forecast_leakage(df)
    print("published numbers")
    check_published_numbers()

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed: {FAILED}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
