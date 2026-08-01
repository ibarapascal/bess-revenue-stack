"""v7 — how much of every headline here is the sample?

Every number in this repository is a point estimate over one 22-month window. The
parameter uncertainty is worked out in detail — c_deg is swept over four inputs, the
ageing ratio over 1.0-2.5, thermal load over 0-0.2 MW — but the *sampling* uncertainty
is not addressed anywhere. "Pricing wear costs 42-78 % of net revenue" reads like a
range but is four point estimates under four assumptions, not a confidence interval:
run the same experiment on a different two years and it would come out somewhere else,
and nothing here says how far.

This adds that dimension without re-solving anything. `run_backtest` already returns a
per-window revenue decomposition, and with `execute_periods=48` a window is exactly one
day, so a 672-day run is a 672-point daily series for every arm. Every headline is a
ratio of sums over that series, which can be resampled directly.

Design points that matter:

  paired resampling      Each draw takes the *same* days from both arms of a comparison.
                         Resampling the arms independently would add a difference that
                         the experiment does not contain — the arms are two treatments
                         of one week of weather, not two samples.

  moving blocks          Daily battery revenue is strongly autocorrelated (weather and
                         fuel prices persist, and weekdays differ from weekends), so
                         an i.i.d. bootstrap would understate the spread. Blocks are
                         circular so that no day is underweighted at the edges.

  block length 7 days    The usual rule of thumb l ~ n^(1/3) gives 8.8 for n = 672, and
                         a 7-day block spans exactly one weekday/weekend cycle. A
                         28-day block is reported alongside as a robustness check; it
                         is three times the rule-of-thumb length and leaves fewer
                         effectively independent blocks, so it is the check and not the
                         headline.

What this does *not* fix: the day-to-day linkage inside the experiment. State of charge
carries from one window into the next, so the daily series is not strictly exchangeable
even within a block. Blocks absorb the short-range part of that; what remains is a
reason to read these intervals as approximate.

Run:  PYTHONPATH=src python3 scripts/v7_bootstrap.py 2024-03-01 2026-01-01
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
from bess.forecast.price import Forecaster
from bess.hardware.converter import ConverterModel
from bess.optimise.dispatch import Battery, DispatchConfig, run_backtest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v5_level_shape import matched_round_trip  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "results"
SEED = 20260801
B = 2000
BLOCK_MAIN, BLOCK_ALT = 7, 28


# --------------------------------------------------------------------------- settling
def settle_windows(chg, dis, prices, battery, cfg, exec_n, curve=None, eta_round_trip=None,
                   fixed_loss_mw=0.0):
    """Settle a fixed schedule, reporting revenue and throughput per execution window.

    Mirrors `dispatch.simulate` (curve) and `v5.simulate_flat` (constant) exactly,
    including the clipping rule, and additionally accumulates per window. The totals
    are asserted against those functions' published outputs in main(), so the
    duplication is checked rather than trusted.
    """
    dt = cfg.dt_hours
    soc = battery.soc_init
    n = len(prices)
    nw = int(np.ceil(n / exec_n))
    rev_w = np.zeros(nw)
    thr_w = np.zeros(nw)
    a = (curve.k2 / curve.p_rated_mw) if curve is not None else None
    eta = float(np.sqrt(eta_round_trip)) if eta_round_trip is not None else None
    for t in range(n):
        w = t // exec_n
        d, c = float(dis[t]), float(chg[t])
        if d > 0:
            avail = max(soc - battery.soc_min, 0.0)
            if curve is not None:
                if (d + a * d ** 2) * dt > avail:
                    d = max((-1.0 + (1.0 + 4.0 * a * avail / dt) ** 0.5) / (2.0 * a), 0.0) \
                        if a > 0 else avail / dt
                soc -= (d + a * d ** 2) * dt
            else:
                if d * dt / eta > avail:
                    d = avail * eta / dt
                soc -= d * dt / eta
        if c > 0:
            room = max(battery.soc_max - soc, 0.0)
            if curve is not None:
                if (c - a * c ** 2) * dt > room:
                    disc = 1.0 - 4.0 * a * room / dt
                    c = max((1.0 - disc ** 0.5) / (2.0 * a), 0.0) \
                        if (a > 0 and disc >= 0) else room / dt
                soc += (c - a * c ** 2) * dt
            else:
                if eta * c * dt > room:
                    c = room / (eta * dt)
                soc += eta * c * dt
        soc = min(max(soc, battery.soc_min), battery.soc_max)
        r = prices[t] * (d - c) * dt
        if cfg.aux_standing_mw:
            r -= prices[t] * cfg.aux_standing_mw * dt
        if (d + c) > 1e-6:
            r -= prices[t] * fixed_loss_mw * dt
        rev_w[w] += r
        thr_w[w] += d * dt
    net_w = rev_w - cfg.c_deg_arbitrage * thr_w
    return {"revenue_energy_w": rev_w, "throughput_w": thr_w, "net_w": net_w}


# ------------------------------------------------------------------------- resampling
def mbb_index(n: int, block: int, rng: np.random.Generator, reps: int) -> np.ndarray:
    """Circular moving-block bootstrap indices, shape (reps, n)."""
    nblocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=(reps, nblocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    return idx.reshape(reps, -1)[:, :n]


def interval(series: dict, fn, n: int, block: int, rng, reps=B) -> dict:
    """Point estimate plus a paired block-bootstrap interval for a ratio of sums.

    `fn` receives summed quantities, so it is evaluated on the resample rather than
    averaged over it: a ratio of sums is not the sum of ratios and resampling the
    ratio per day would answer a different question.
    """
    point = fn({k: float(v.sum()) for k, v in series.items()})
    idx = mbb_index(n, block, rng, reps)
    vals = np.empty(reps)
    for b in range(reps):
        i = idx[b]
        vals[b] = fn({k: float(v[i].sum()) for k, v in series.items()})
    q = np.percentile(vals, [2.5, 25, 50, 75, 97.5])
    return {"point": point, "median": q[2], "p2.5": q[0], "p25": q[1],
            "p75": q[3], "p97.5": q[4], "iqr": q[3] - q[1],
            "ci_width": q[4] - q[0],
            "covers_zero": bool(q[0] <= 0 <= q[4])}


def by_quarter(series: dict, fn, stamps: pd.Series) -> list:
    """The same estimate computed inside each calendar quarter."""
    # tz_convert(None) first: to_period would otherwise drop the timezone with a warning
    # and fall back to exactly this naive UTC wall time, so being explicit changes the
    # noise and not the labels.
    lab = stamps.dt.tz_convert(None).dt.to_period("Q").astype(str).to_numpy()
    out = []
    for q in pd.unique(lab):
        m = lab == q
        if m.sum() < 20:            # a stub quarter is not an estimate
            continue
        # `days` matters when reading the range: the window opens on 1 March, so its
        # first calendar quarter holds one month, and that 31-day bucket carries the
        # extreme value for several quantities here. It is reported rather than dropped,
        # but a 31-day bucket and a 92-day one are not the same kind of observation.
        out.append({"quarter": q, "days": int(m.sum()),
                    "value": fn({k: float(v[m].sum()) for k, v in series.items()})})
    return out


def report(name, series, fn, stamps, rng, unit=""):
    n = len(next(iter(series.values())))
    main = interval(series, fn, n, BLOCK_MAIN, rng)
    alt = interval(series, fn, n, BLOCK_ALT, rng)
    qs = by_quarter(series, fn, stamps)
    vals = [q["value"] for q in qs]
    full = [q["value"] for q in qs if q["days"] >= 80]
    row = {
        "quantity": name, "unit": unit,
        "point": round(main["point"], 2),
        "boot_median": round(main["median"], 2),
        "ci95_lo": round(main["p2.5"], 2), "ci95_hi": round(main["p97.5"], 2),
        "iqr_lo": round(main["p25"], 2), "iqr_hi": round(main["p75"], 2),
        "ci95_width": round(main["ci_width"], 2),
        "ci95_lo_28d": round(alt["p2.5"], 2), "ci95_hi_28d": round(alt["p97.5"], 2),
        "quarters_min": round(min(vals), 2) if vals else None,
        "quarters_max": round(max(vals), 2) if vals else None,
        "n_quarters": len(qs),
    }
    print(f"  {name:44s} {main['point']:8.2f}{unit}  95% [{main['p2.5']:7.2f},{main['p97.5']:7.2f}]"
          f"  IQR [{main['p25']:7.2f},{main['p75']:7.2f}]"
          f"  quarters [{min(vals):7.2f},{max(vals):7.2f}]"
          f"  full only [{min(full):7.2f},{max(full):7.2f}]" if vals else "")
    return row, qs


def main(start: str, end: str):
    OUT.mkdir(exist_ok=True)
    rng = np.random.default_rng(SEED)
    df = market_index(date.fromisoformat(start),
                      date.fromisoformat(end)).dropna(subset=["price"]).reset_index(drop=True)
    prices = df.price.to_numpy(float)
    batt = Battery(power_mw=50, energy_mwh=100)
    conv = ConverterModel(p_rated_mw=batt.power_mw)
    dc = DegradationCost(cell_model="prismatic_250ah")
    c_arb, c_fr = dc.cost("arbitrage"), dc.cost("frequency")
    EX = 48

    def stamps_for(nw, frame=None):
        f = df if frame is None else frame
        return pd.to_datetime(f.start_time.to_numpy()[::EX][:nw], utc=True).to_series(
            index=range(nw))

    rows, quarters = [], {}
    print(f"periods={len(df):,}  windows(days)={len(df)//EX}  B={B}  "
          f"blocks {BLOCK_MAIN}d (main) / {BLOCK_ALT}d (check)  seed={SEED}\n")

    # ---- finding 1: pricing wear -------------------------------------------------
    print("finding 1 — pricing degradation")
    free = run_backtest(df, batt, DispatchConfig(c_deg_arbitrage=0.0, allow_frequency=False),
                        window_periods=96, execute_periods=EX)
    deg_arms = {}
    for lbl, loss, efc, yrs in (("italian", 0.0137, 118.7, 3.0),
                                ("german", 0.03, 300.0, 8.0)):
        c = DegradationCost(cell_model="prismatic_250ah", field_annual_loss=loss,
                            field_efc_per_year=efc, field_years=yrs).cost("arbitrage")
        deg_arms[lbl] = run_backtest(df, batt,
                                     DispatchConfig(c_deg_arbitrage=c, allow_frequency=False),
                                     window_periods=96, execute_periods=EX)
    nw = len(free["windows"])
    st = stamps_for(nw)
    for lbl in deg_arms:
        s = {"free": free["windows"].revenue_net.to_numpy(),
             "priced": deg_arms[lbl]["windows"].revenue_net.to_numpy()[:nw]}
        r, q = report(f"deg overstatement, {lbl} c_deg",
                      s, lambda d: (d["free"] / d["priced"] - 1) * 100, st, rng, " %")
        rows.append(r); quarters[r["quantity"]] = q

    # ---- finding 2: reserve headroom ---------------------------------------------
    print("\nfinding 2 — SOC headroom")
    for fr in (2.0, 5.0, 10.0, 20.0):
        d2 = df.copy(); d2["fr_price"] = fr
        arms = {}
        for hr in (True, False):
            arms[hr] = run_backtest(d2, batt,
                                    DispatchConfig(c_deg_arbitrage=c_arb, c_deg_frequency=c_fr,
                                                   allow_frequency=True, reserve_headroom=hr),
                                    fr_col="fr_price", window_periods=96, execute_periods=EX)
        s = {"with": arms[True]["windows"].revenue_net.to_numpy(),
             "without": arms[False]["windows"].revenue_net.to_numpy()}
        r, q = report(f"headroom overstatement @ GBP{fr:.0f}/MW/h",
                      s, lambda d: (d["without"] / d["with"] - 1) * 100, st, rng, " %")
        rows.append(r); quarters[r["quantity"]] = q

    # ---- finding 4: the efficiency assumption ------------------------------------
    print("\nfinding 4 — the efficiency assumption (and its level/shape split)")
    conventional = run_backtest(df, batt,
                                DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False),
                                window_periods=96, execute_periods=EX)
    sc = conventional["schedule"]
    chg, dis = sc.charge_mw.to_numpy(float), sc.discharge_mw.to_numpy(float)
    p = prices[:len(sc)]
    m = matched_round_trip(chg, dis, conv)
    flat_rt = batt.eta_charge * batt.eta_discharge
    settles = {}
    for lbl, kw in (("flat", {"eta_round_trip": flat_rt}),
                    ("matched", {"eta_round_trip": m["round_trip"]}),
                    ("curve", {"curve": conv})):
        settles[lbl] = settle_windows(chg, dis, p, batt,
                                      DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False),
                                      EX, fixed_loss_mw=conv.fixed_loss_mw, **kw)
    # duplication check against the published aggregates before anything is read from it
    v3 = json.loads((OUT / "v3_converter_efficiency.json").read_text())["table"][0]
    v5 = json.loads((OUT / "v5_level_shape.json").read_text())["table"][0]
    for lbl, target, src in (("flat", v3["with_aux_net_GBP"], "v3 with_aux"),
                             ("curve", v3["actual_net_GBP"], "v3 actual"),
                             ("matched", v5["flat_matched_net_GBP"], "v5 matched")):
        got = float(settles[lbl]["net_w"].sum())
        assert abs(got - target) < 2, f"{lbl} settle {got:,.0f} != {src} {target:,}"
    print(f"  [ok] per-window settlement reproduces v3/v5 aggregates to within GBP2")

    nwc = len(settles["flat"]["net_w"])
    stc = stamps_for(nwc)
    s = {"conv": conventional["windows"].revenue_net.to_numpy()[:nwc],
         "curve": settles["curve"]["net_w"]}
    r, q = report("conventional overstatement, no thermal",
                  s, lambda d: (d["conv"] / d["curve"] - 1) * 100, stc, rng, " %")
    rows.append(r); quarters[r["quantity"]] = q

    s = {"flat": settles["flat"]["net_w"], "matched": settles["matched"]["net_w"],
         "curve": settles["curve"]["net_w"]}
    r, q = report("shape share of the efficiency term",
                  s, lambda d: (d["curve"] - d["matched"]) /
                               (d["curve"] - d["flat"]) * 100, stc, rng, " %")
    rows.append(r); quarters[r["quantity"]] = q

    # ---- finding 5: service-differentiated wear ----------------------------------
    print("\nfinding 5 — wear priced by service")
    for fr in (2.0, 5.0, 10.0):
        d2 = df.copy(); d2["fr_price"] = fr
        arms = {}
        for ratio in (1.0, 1.85):
            arms[ratio] = run_backtest(d2, batt,
                                       DispatchConfig(c_deg_arbitrage=c_arb,
                                                      c_deg_frequency=c_arb / ratio,
                                                      allow_frequency=True,
                                                      reserve_headroom=True),
                                       fr_col="fr_price", window_periods=96, execute_periods=EX)
        s = {"flat": arms[1.0]["windows"].revenue_net.to_numpy(),
             "diff": arms[1.85]["windows"].revenue_net.to_numpy()}
        r, q = report(f"service-differentiation gain @ GBP{fr:.0f}/MW/h",
                      s, lambda d: (d["diff"] / d["flat"] - 1) * 100, st, rng, " %")
        rows.append(r); quarters[r["quantity"]] = q

    # ---- finding 3: capture rate -------------------------------------------------
    print("\nfinding 3 — capture rate (own window, forecast-driven)")
    raw = market_index(date(2024, 1, 1), date(2025, 12, 31)).dropna(
        subset=["price"]).reset_index(drop=True)
    frames = {k: Forecaster(kind=k).run(raw) for k in ("persistence", "gbm")}
    common = min(len(frames["persistence"]), len(frames["gbm"]))
    base = frames["gbm"].tail(common).reset_index(drop=True)
    base["fc_persistence"] = frames["persistence"].tail(common).reset_index(drop=True)["forecast"].to_numpy()
    base = base.rename(columns={"forecast": "fc_gbm"})
    cfg_c = DispatchConfig(c_deg_arbitrage=c_arb, allow_frequency=False)
    pf = run_backtest(base, batt, cfg_c, window_periods=96, execute_periods=EX)
    caps = {}
    for kind, col in (("persistence", "fc_persistence"), ("gbm", "fc_gbm")):
        fc = base[["price"]].copy(); fc["price"] = base[col].to_numpy()
        caps[kind] = run_backtest(base, batt, cfg_c, window_periods=96,
                                  execute_periods=EX, forecast=fc)
    nwf = len(pf["windows"])
    stf = stamps_for(nwf, base)
    for kind in ("gbm", "persistence"):
        s = {"pf_net": pf["windows"].revenue_net.to_numpy(),
             "fc_net": caps[kind]["windows"].revenue_net.to_numpy()[:nwf],
             "pf_gross": pf["windows"].revenue_energy.to_numpy(),
             "fc_gross": caps[kind]["windows"].revenue_energy.to_numpy()[:nwf]}
        r, q = report(f"net capture, {kind}",
                      s, lambda d: d["fc_net"] / d["pf_net"] * 100, stf, rng, " %")
        rows.append(r); quarters[r["quantity"]] = q
        r, q = report(f"gross capture, {kind}",
                      s, lambda d: d["fc_gross"] / d["pf_gross"] * 100, stf, rng, " %")
        rows.append(r); quarters[r["quantity"]] = q

    res = pd.DataFrame(rows)
    res.to_csv(OUT / "v7_bootstrap.csv", index=False)
    qrows = [{"quantity": k, **v} for k, vs in quarters.items() for v in vs]
    pd.DataFrame(qrows).to_csv(OUT / "v7_quarters.csv", index=False)
    (OUT / "v7_bootstrap.json").write_text(json.dumps({
        "window": [start, end], "battery": "50 MW / 100 MWh (2 h)",
        "method": {
            "resample_unit": "one execution window = 48 half-hours = 1 day",
            "n_days": int(len(df) // EX), "replicates": B, "seed": SEED,
            "block_days_main": BLOCK_MAIN, "block_days_check": BLOCK_ALT,
            "block_choice": ("l ~ n^(1/3) gives 8.8 for n=672 and a 7-day block spans one "
                             "weekday/weekend cycle; 28 days is three times the rule of "
                             "thumb and is reported as a check, not as the headline"),
            "paired": ("both arms of every comparison are read at the same resampled days, "
                       "because the arms are two treatments of one history rather than two "
                       "samples"),
            "estimator": "ratio of sums, recomputed on each resample",
            "caveat": ("state of charge carries between windows, so the daily series is not "
                       "strictly exchangeable even within a block; the intervals are "
                       "approximate for that reason"),
        },
        "table": rows,
    }, indent=2))
    print(f"\nwritten: {OUT/'v7_bootstrap.csv'}  and  {OUT/'v7_quarters.csv'}")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "2024-03-01"
    b = sys.argv[2] if len(sys.argv) > 2 else "2026-01-01"
    main(a, b)
