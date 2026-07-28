"""
Verification suite — the checks that would catch the errors that actually happened.

Every check here exists because something went wrong once. A model that solves and
produces plausible numbers is not evidence of correctness; these are the invariants
that distinguish the two.

Run:  PYTHONPATH=src python3 scripts/verify.py
"""
from __future__ import annotations

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
from bess.optimise.dispatch import Battery, DispatchConfig, solve_window

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
    eff = conv.round_trip(np.array([0.1, 1.0]) * 50)
    check("converter reproduces its calibration points",
          abs(eff[0] - 0.65) < 0.01 and abs(eff[1] - 0.85) < 0.01,
          f"round trip {eff[0]:.3f} at 10 % load, {eff[1]:.3f} at rated")


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
    print("forecasting")
    check_forecast_leakage(df)

    print()
    if FAILED:
        print(f"{len(FAILED)} check(s) failed: {FAILED}")
        sys.exit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
