"""v8 — how much of the capture-rate shortfall is the forecast, and how much is the program?

Finding 3 reports that a LightGBM day-ahead forecast captures 48 % of perfect-foresight
net revenue. That number is read on this page as a statement about forecast quality, but
it is produced by a *deterministic* program: a single price path is handed to an LP that
then plans as though it were certain. Two quite different things are bundled inside the
52 % shortfall — the forecast not knowing the prices, and the optimiser not knowing that
it does not know.

The second is a modelling choice and can be removed. This builds a scenario set from
quantile forecasts and solves a two-stage program: the periods that will actually be
executed are decided once, before the uncertainty resolves, and the rest of the horizon
is allowed to differ by scenario. Settlement is on realised prices throughout, exactly as
in v2.

    perfect foresight            100 %
    deterministic point forecast  48 %   <- what finding 3 reports
    two-stage scenario program     ? %   <- the difference is the architecture
    the remainder                        <- genuinely not knowing the price

One prediction worth writing down before running it, because it constrains how large the
effect can be. With a risk-neutral linear objective the first-stage revenue term is
sum_s w_s * p_s(t) * (dis - chg), which collapses to the *mean* forecast path. So the
two-stage program cannot differ from a mean-forecast deterministic program through the
objective at all — it can only differ through the recourse structure, i.e. by valuing the
state of charge it hands over to an uncertain continuation. Any gap found here is that
channel alone, and a small one would be the honest expected result rather than a
disappointment. A risk-averse variant is run alongside precisely because it is the thing
that *can* move the first-stage decision.

Known limitation, stated because it bounds what the scenario set can represent: pointwise
quantile paths are comonotone. The q10 path is low in every period at once, which is not
how a price series behaves — real uncertainty reshuffles *which* periods are cheap, and
that is the uncertainty a battery is actually exposed to. So this scenario set
understates the diversity of futures and the recourse value measured against it is a
lower bound.

Run:  PYTHONPATH=src python3 scripts/v8_stochastic.py 2024-01-01 2025-12-31
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pulp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bess.data.elexon import market_index
from bess.degradation.blast_lfp import DegradationCost
from bess.forecast.price import FEATURES, build_features
from bess.optimise.dispatch import Battery, DispatchConfig, run_backtest

OUT = Path(__file__).resolve().parents[1] / "results"
# Fitting five quantile models over ~100 expanding-window origins is by far the expensive
# part here, and it is pure input to the dispatch stage, so it is cached beside the market
# data (git-ignored) rather than recomputed. On an 8 GB box the two stages also should not
# be resident at once: LightGBM training and CBC both want memory, and a CBC fork failed
# outright while the trainer was running. Splitting them is what makes the run survivable,
# not merely faster on a repeat.
CACHE = Path(__file__).resolve().parents[1] / "data" / "cache" / "v8_quantiles.parquet"
QUANTILES = [0.1, 0.25, 0.5, 0.75, 0.9]
N_JOBS = 2          # cap trainer threads: the box is small and CBC needs room beside it


def quantile_forecasts(df: pd.DataFrame, quantiles=QUANTILES, retrain_every_days=7,
                       min_train_periods=48 * 60) -> pd.DataFrame:
    """One LightGBM per quantile, refit on an expanding window before each origin.

    Same leakage discipline as `forecast.price`: features are lags only, and each model
    is fit strictly on data before the origin it predicts. Deliberately a separate
    implementation from the point forecaster rather than an edit to it, so that no v2
    number can move.
    """
    import lightgbm as lgb

    d = build_features(df)
    n = len(d)
    start = max(min_train_periods, 336 + 336 + 48)
    step = retrain_every_days * 48
    cols = {q: np.full(n, np.nan) for q in quantiles}
    for origin in range(start, n, step):
        train = d.iloc[:origin].dropna(subset=FEATURES + ["price"])
        if len(train) < 500:
            continue
        stop = min(origin + step, n)
        block = d.iloc[origin:stop]
        ok = block[FEATURES].notna().all(axis=1)
        if not ok.any():
            continue
        X = block.loc[ok, FEATURES]
        for q in quantiles:
            m = lgb.LGBMRegressor(objective="quantile", alpha=q, n_estimators=300,
                                  learning_rate=0.05, num_leaves=31, min_child_samples=30,
                                  colsample_bytree=0.9, verbose=-1, random_state=42,
                                  n_jobs=N_JOBS)
            m.fit(train[FEATURES], train["price"])
            cols[q][origin:stop][ok.to_numpy()] = m.predict(X)
    for q in quantiles:
        d[f"q{int(q*100)}"] = cols[q]
    keep = [f"q{int(q*100)}" for q in quantiles]
    return d.iloc[start:].dropna(subset=keep).reset_index(drop=True)


def calibration(df: pd.DataFrame, quantiles=QUANTILES) -> list:
    """Coverage and pinball loss. A scenario set built from miscalibrated quantiles is
    not a probability statement, so this is reported before anything is built on it."""
    y = df["price"].to_numpy(float)
    out = []
    for q in quantiles:
        f = df[f"q{int(q*100)}"].to_numpy(float)
        e = y - f
        pin = float(np.mean(np.maximum(q * e, (q - 1) * e)))
        out.append({"quantile": q, "empirical_coverage": float(np.mean(y <= f)),
                    "pinball_loss": pin, "mean_level": float(np.mean(f))})
    return out


def solve_two_stage(scen: np.ndarray, weights: np.ndarray, battery: Battery,
                    cfg: DispatchConfig, exec_n: int, soc_start: float,
                    cvar_alpha: float | None = None) -> dict:
    """Two-stage dispatch. First `exec_n` periods are one decision for all scenarios.

    scen has shape (n_scenarios, T). The first-stage variables carry no scenario index,
    which is the non-anticipativity constraint stated structurally rather than as a
    penalty. After exec_n every scenario gets its own recourse.

    cvar_alpha turns the objective from the expectation into a CVaR at that level, via
    the Rockafellar-Uryasev linearisation. That is the variant that can actually change
    the first-stage decision, because a linear expectation cannot.
    """
    S, T = scen.shape
    dt = cfg.dt_hours
    m = pulp.LpProblem("v8", pulp.LpMaximize)

    chg0 = [pulp.LpVariable(f"c0_{t}", 0, battery.power_mw) for t in range(exec_n)]
    dis0 = [pulp.LpVariable(f"d0_{t}", 0, battery.power_mw) for t in range(exec_n)]
    soc0 = [pulp.LpVariable(f"s0_{t}", battery.soc_min, battery.soc_max)
            for t in range(exec_n + 1)]
    m += soc0[0] == soc_start
    for t in range(exec_n):
        m += soc0[t + 1] == soc0[t] + battery.eta_charge * chg0[t] * dt \
             - dis0[t] * dt / battery.eta_discharge

    profits = []
    for s in range(S):
        tail = range(exec_n, T)
        # Prefix "sc" keeps scenario names disjoint from the first-stage c0_/d0_/s0_
        # family: without it scenario 0's soc at t=exec_n collides with soc0's last
        # entry (both "s0_48"), and the LP file CBC receives has one name bound to two
        # variables — which CBC rejects at load, not at solve.
        cs = {t: pulp.LpVariable(f"sc_c{s}_{t}", 0, battery.power_mw) for t in tail}
        ds = {t: pulp.LpVariable(f"sc_d{s}_{t}", 0, battery.power_mw) for t in tail}
        ss = {t: pulp.LpVariable(f"sc_s{s}_{t}", battery.soc_min, battery.soc_max)
              for t in range(exec_n, T + 1)}
        m += ss[exec_n] == soc0[exec_n]
        for t in tail:
            m += ss[t + 1] == ss[t] + battery.eta_charge * cs[t] * dt \
                 - ds[t] * dt / battery.eta_discharge
        p = scen[s]
        first = pulp.lpSum(p[t] * (dis0[t] - chg0[t]) * dt for t in range(exec_n)) \
            - pulp.lpSum(cfg.c_deg_arbitrage * dis0[t] * dt for t in range(exec_n))
        rest = pulp.lpSum(p[t] * (ds[t] - cs[t]) * dt for t in tail) \
            - pulp.lpSum(cfg.c_deg_arbitrage * ds[t] * dt for t in tail)
        profits.append(first + rest)

    if cvar_alpha is None:
        m += pulp.lpSum(weights[s] * profits[s] for s in range(S))
    else:
        # CVaR_alpha = max_eta  eta - 1/(1-alpha) * E[(eta - profit)+]
        eta = pulp.LpVariable("eta")
        dev = [pulp.LpVariable(f"z_{s}", 0, None) for s in range(S)]
        for s in range(S):
            m += dev[s] >= eta - profits[s]
        m += eta - (1.0 / (1.0 - cvar_alpha)) * pulp.lpSum(weights[s] * dev[s]
                                                           for s in range(S))

    if pulp.LpStatus[m.solve(pulp.PULP_CBC_CMD(msg=0))] != "Optimal":
        raise RuntimeError("scenario program did not solve")
    v = lambda x: (x.value() or 0.0)
    return {"charge_mw": np.array([v(x) for x in chg0]),
            "discharge_mw": np.array([v(x) for x in dis0]),
            "soc_end": v(soc0[exec_n])}


def backtest_scenarios(df: pd.DataFrame, scen_cols: list, weights: np.ndarray,
                       battery: Battery, cfg: DispatchConfig, window=96, exec_n=48,
                       cvar_alpha=None) -> dict:
    """Roll the two-stage program and settle on realised prices."""
    actual = df["price"].to_numpy(float)
    S = np.vstack([df[c].to_numpy(float) for c in scen_cols])
    soc = battery.soc_init
    rows, sched = [], []
    for i in range(0, len(actual) - 1, exec_n):
        j = min(i + window, len(actual))
        if j - i < 2:
            break
        k = min(exec_n, j - i)
        r = solve_two_stage(S[:, i:j], weights, battery, cfg, k, soc, cvar_alpha)
        chg, dis = r["charge_mw"][:k], r["discharge_mw"][:k]
        p_act = actual[i:i + k]
        rev = float(np.sum(p_act * (dis - chg) * cfg.dt_hours))
        cost = float(cfg.c_deg_arbitrage * np.sum(dis) * cfg.dt_hours)
        soc = r["soc_end"]
        rows.append({"i0": i, "revenue_energy": rev, "cost_degradation": cost,
                     "revenue_net": rev - cost,
                     "throughput_mwh": float(np.sum(dis) * cfg.dt_hours)})
        sched.append(pd.DataFrame({"charge_mw": chg, "discharge_mw": dis}))
    w = pd.DataFrame(rows)
    days = len(actual) * cfg.dt_hours / 24.0
    return {"windows": w, "schedule": pd.concat(sched, ignore_index=True),
            "revenue_energy": float(w.revenue_energy.sum()),
            "cost_degradation": float(w.cost_degradation.sum()),
            "revenue_net": float(w.revenue_net.sum()),
            "throughput_mwh": float(w.throughput_mwh.sum()),
            "efc": float(w.throughput_mwh.sum() / battery.energy_mwh),
            "days": days}


def stage_forecast(start: str, end: str) -> pd.DataFrame:
    """Fit and cache the quantile forecasts. Idempotent: reuses the cache if present."""
    if CACHE.exists():
        d = pd.read_parquet(CACHE)
        print(f"quantile forecasts read from cache: {len(d):,} periods", flush=True)
        return d
    raw = market_index(date.fromisoformat(start),
                       date.fromisoformat(end)).dropna(subset=["price"]).reset_index(drop=True)
    print(f"raw periods={len(raw):,}", flush=True)
    d = quantile_forecasts(raw)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    keep = ["start_time", "settlement_period", "price"] + [f"q{int(q*100)}" for q in QUANTILES]
    d[keep].to_parquet(CACHE, index=False)
    print(f"quantile forecasts cached: {len(d):,} periods "
          f"{d.start_time.min().date()} .. {d.start_time.max().date()}", flush=True)
    return d[keep]


def main(start: str, end: str, stage: str = "all"):
    OUT.mkdir(exist_ok=True)
    d = stage_forecast(start, end)
    if stage == "forecast":
        print("stage 1 complete; rerun with stage=dispatch", flush=True)
        return

    cal = calibration(d)
    print("\ncalibration (empirical coverage should track the nominal quantile)")
    for c in cal:
        print(f"  q{int(c['quantile']*100):02d}  coverage {c['empirical_coverage']:.3f}"
              f"  pinball {c['pinball_loss']:6.3f}  mean level {c['mean_level']:7.2f}",
              flush=True)

    batt = Battery(power_mw=50, energy_mwh=100)
    dc = DegradationCost(cell_model="prismatic_250ah")
    cfg = DispatchConfig(c_deg_arbitrage=dc.cost("arbitrage"), allow_frequency=False)
    qcols = [f"q{int(q*100)}" for q in QUANTILES]
    # Equal weights: the quantiles are equally spaced in probability only between q25 and
    # q75, so this is a convenience, not a density. Stated rather than dressed up.
    w = np.ones(len(QUANTILES)) / len(QUANTILES)

    print("\narms", flush=True)
    pf = run_backtest(d, batt, cfg, window_periods=96, execute_periods=48)
    print(f"  perfect foresight      net {pf['revenue_net']:>12,.0f}", flush=True)

    fc50 = d[["price"]].copy(); fc50["price"] = d["q50"].to_numpy()
    det = run_backtest(d, batt, cfg, window_periods=96, execute_periods=48, forecast=fc50)
    print(f"  deterministic q50      net {det['revenue_net']:>12,.0f}"
          f"  ({det['revenue_net']/pf['revenue_net']*100:5.1f} %)", flush=True)

    mean_col = "qmean"
    d[mean_col] = d[qcols].mean(axis=1)
    fcm = d[["price"]].copy(); fcm["price"] = d[mean_col].to_numpy()
    detm = run_backtest(d, batt, cfg, window_periods=96, execute_periods=48, forecast=fcm)
    print(f"  deterministic q-mean   net {detm['revenue_net']:>12,.0f}"
          f"  ({detm['revenue_net']/pf['revenue_net']*100:5.1f} %)", flush=True)

    sto = backtest_scenarios(d, qcols, w, batt, cfg)
    print(f"  two-stage, risk neutral net {sto['revenue_net']:>12,.0f}"
          f"  ({sto['revenue_net']/pf['revenue_net']*100:5.1f} %)", flush=True)

    cv = backtest_scenarios(d, qcols, w, batt, cfg, cvar_alpha=0.5)
    print(f"  two-stage, CVaR(0.5)   net {cv['revenue_net']:>12,.0f}"
          f"  ({cv['revenue_net']/pf['revenue_net']*100:5.1f} %)", flush=True)

    def cap(x):
        return x["revenue_net"] / pf["revenue_net"] * 100

    rows = [
        {"arm": "perfect foresight", "net_GBP": round(pf["revenue_net"]),
         "capture_net_pct": 100.0, "efc_per_year": round(pf["efc"] / pf["days"] * 365, 1)},
        {"arm": "deterministic, q50", "net_GBP": round(det["revenue_net"]),
         "capture_net_pct": round(cap(det), 1),
         "efc_per_year": round(det["efc"] / det["days"] * 365, 1)},
        {"arm": "deterministic, mean of quantiles", "net_GBP": round(detm["revenue_net"]),
         "capture_net_pct": round(cap(detm), 1),
         "efc_per_year": round(detm["efc"] / detm["days"] * 365, 1)},
        {"arm": "two-stage scenario, risk neutral", "net_GBP": round(sto["revenue_net"]),
         "capture_net_pct": round(cap(sto), 1),
         "efc_per_year": round(sto["efc"] / sto["days"] * 365, 1)},
        {"arm": "two-stage scenario, CVaR 0.5", "net_GBP": round(cv["revenue_net"]),
         "capture_net_pct": round(cap(cv), 1),
         "efc_per_year": round(cv["efc"] / cv["days"] * 365, 1)},
    ]
    pd.DataFrame(rows).to_csv(OUT / "v8_stochastic.csv", index=False)
    pd.DataFrame(cal).to_csv(OUT / "v8_calibration.csv", index=False)

    arch = cap(sto) - cap(detm)
    (OUT / "v8_stochastic.json").write_text(json.dumps({
        "window": [start, end], "battery": "50 MW / 100 MWh (2 h)",
        "quantiles": QUANTILES, "scenario_weights": "equal",
        "calibration": cal,
        "decomposition": {
            "deterministic_capture_pct": round(cap(detm), 1),
            "scenario_capture_pct": round(cap(sto), 1),
            "architecture_gain_pct_points": round(arch, 2),
            "remaining_shortfall_pct_points": round(100 - cap(sto), 1),
        },
        "prediction_stated_before_running": (
            "with a risk-neutral linear objective the first-stage revenue term collapses "
            "to the mean forecast path, so the two-stage program can differ from a "
            "mean-forecast deterministic one only through the recourse structure; a small "
            "gain is the expected result"),
        "scenario_set_limitation": (
            "pointwise quantile paths are comonotone — q10 is low in every period at once "
            "— whereas real uncertainty reshuffles which periods are cheap. The scenario "
            "set therefore understates the diversity of futures and the recourse value "
            "measured against it is a lower bound"),
        "table": rows,
    }, indent=2))
    print(f"\narchitecture worth {arch:+.2f} points of capture; "
          f"{100 - cap(sto):.1f} points remain unexplained by it", flush=True)
    print(f"written: {OUT/'v8_stochastic.csv'}", flush=True)


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2024-01-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2025-12-31"
    s = sys.argv[3] if len(sys.argv) > 3 else "all"
    main(a, b, s)
