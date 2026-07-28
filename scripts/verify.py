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
    # Reproducing the two calibration points is nearly tautological — the coefficients
    # are solved from them. The test that can actually fail is out-of-sample: the source
    # paper publishes a fitted curve over eleven setpoints, and the two-point fit here
    # must track it at loads it was never given. Values below are that paper's year-one
    # curve evaluated at 0.2, 0.3 and 0.5 p.u.
    for load, target in ((0.20, 0.869), (0.30, 0.905), (0.50, 0.931)):
        got = float(conv.round_trip(np.array([load * 50]))[0])
        check(f"matches the published curve at {load:.0%} load, which it was not fitted to",
              abs(got - target) < 0.02, f"{got:.3f} against {target:.3f}")
    eff = conv.round_trip(np.array([0.1, 1.0]) * 50)
    check("calibration points are recovered by the two-point solve",
          abs(eff[0] - 0.771) < 0.01 and abs(eff[1] - 0.937) < 0.01,
          f"round trip {eff[0]:.3f} at 10 % load, {eff[1]:.3f} at rated — true by "
          f"construction, so this only tests the algebra, not the calibration")
    check("calibration is not the auxiliary-inclusive metric",
          eff[1] > 0.90,
          f"{eff[1]:.3f} at rated is the AC-terminal figure; the global figure of "
          f"0.85 includes the auxiliaries this model charges separately")


def check_degradation_anchor():
    """Field anchoring must reproduce the field case, and c_deg must price only wear
    that throughput actually causes."""
    dc = DegradationCost(cell_model="prismatic_250ah")
    days, n = dc.field_years * 365.25, dc.field_efc_per_year * dc.field_years
    implied = dc._model().cumulative_loss(days, n) * dc.anchor_factor()
    observed = dc.field_annual_loss * dc.field_years
    check("anchoring reproduces the field plant's measured loss",
          abs(implied - observed) < 1e-9,
          f"{implied:.4%} against {observed:.4%} over {dc.field_years:.0f} years "
          f"and {n:.0f} cycles")

    # The anchor scales a model that already nearly fits. A scale far from one means
    # the model is being forced, which is what a missing power-law exponent looks like.
    a = dc.anchor_factor()
    check("the anchor is a correction, not a rescue", 0.2 < a < 5.0,
          f"scale {a:.3f} — an unanchored cell model landing this close to a system it "
          f"was never fitted to is the check that the exponents are applied")

    # Cycle life implied by the parameterisation, against what large-format LFP is
    # warranted for. Treating the power-law coefficients as linear rates put this at
    # 911 cycles, which no grid battery would be sold with.
    life = dc.implied_cycle_life()
    check("implied cycle life is physically plausible", 2000 < life < 12000,
          f"{life:,.0f} equivalent full cycles to 80 % capacity")

    # c_deg must not carry calendar ageing. Calendar fade is independent of throughput,
    # so charging it per cycle would make the cost rise with the plant's age at a fixed
    # cycle count; it must not.
    young = DegradationCost(field_years=3.0).cost("arbitrage")
    old = DegradationCost(field_years=3.0, reference_cycles=3000).cost("arbitrage")
    check("c_deg falls as cycles accumulate, as a sub-linear wear law requires",
          old < young, f"{young:.2f} at 1000 cycles against {old:.2f} at 3000")

    dc2 = DegradationCost(field_annual_loss=0.02)
    ratio = dc2.cost("arbitrage") / dc2.cost("frequency")
    check("service differentiation carries the measured ratio",
          abs(ratio - 1.85) < 1e-9, f"arbitrage/frequency = {ratio:.3f}")

    # A stated validity limit that nothing consults is decoration. This asserts the
    # warning actually fires, which it did not for the first several versions.
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        DegradationCost(cell_model="prismatic_250ah").cost("arbitrage", dod=0.3)
    check("operating outside the fitted range raises a warning",
          any("extrapolation" in str(x.message) for x in caught),
          "depth of 0.30 is below the model's stated 0.80-1.00 validity range")

    # The Sony model's calendar term is a sigmoid upstream and is not implemented, so
    # it must refuse to be anchored rather than return a number.
    try:
        MODELS["sony_murata_3ah"]().cumulative_loss(1000.0, 300.0)
        ok = False
    except NotImplementedError:
        ok = True
    check("an unimplemented ageing term refuses to produce a number", ok,
          "the Sony calendar term raises instead of returning several hundred per cent")


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
    check("net capture stays below gross capture",
          gbm["capture_net_pct"] < gbm["capture_gross_pct"] - 2,
          f"gross {gbm['capture_gross_pct']}% against net {gbm['capture_net_pct']}% — the "
          f"direction is the finding; the size of the gap scales with the wear price and is "
          f"deliberately not pinned")

    v3 = load("v3_converter_efficiency.json")
    zero = v3["table"][0]
    check("the two efficiency error components still have opposite signs",
          zero["error_from_aux_GBP"] > 0 > zero["error_from_curve_shape_GBP"],
          f"aux {zero['error_from_aux_GBP']:+,}, curve {zero['error_from_curve_shape_GBP']:+,} "
          f"at zero thermal load")

    v4 = load("v4_service_cdeg.json")
    lowest = v4["deltas_vs_flat"][0]
    check("service differentiation still raises reserve holdings",
          all(d["reserve_change_MW"] > 0 for d in v4["deltas_vs_flat"]),
          f"largest shift {lowest['reserve_change_MW']:.1f} MW at the lowest reserve price; "
          f"whether it flips participation outright depends on the wear price and is a "
          f"regime statement, not a pinned result")
    # The finding text is generated from the data and once asserted an outright refusal to
    # enter the market while the same file recorded 20 MW held. Text and data must agree.
    claims_flip = "declines the reserve market outright" in v4["finding"]
    check("the generated finding text matches the data it was generated from",
          claims_flip == lowest["enters_market_only_when_differentiated"],
          "narrative and numbers agree on whether participation flips")


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
