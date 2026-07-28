"""
Capacity-allocation dispatch for a single grid-scale battery.

The framing matters: a battery does not "stack" revenues, it *allocates* one MW
and one MWh across competing uses. Every constraint below exists to stop the
model selling the same capability twice.

    max  sum_t [ p_spot(t) * (P_dis(t) - P_chg(t)) * dt          energy arbitrage
               + p_fr(t) * R(t)                                   availability payment
               ]
         - c_deg_arb * sum_t P_dis(t) * dt
         - c_deg_fr  * sum_t R(t) * util * dt                     expected FR throughput

    s.t. (1) SOC(t+1) = SOC(t) + eta_c*P_chg*dt - P_dis*dt/eta_d
         (2) P_dis(t) + R(t) <= P_max ,  P_chg(t) + R(t) <= P_max
         (3) SOC(t) - SOC_min >= R(t) * T_deliver     (headroom to actually deliver)
             SOC_max - SOC(t) >= R(t) * T_deliver
         (4) SOC_min <= SOC(t) <= SOC_max
         (5) no simultaneous charge and discharge (binary, optional)

Constraint (3) is the one most often missing from published models. Without it
the battery can be paid for holding reserve it has no energy to deliver, and
stacked revenue is overstated by construction. `reserve_headroom=False` exists
solely to measure that overstatement.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pulp


@dataclass
class Battery:
    power_mw: float = 50.0
    energy_mwh: float = 100.0          # 2 h duration, the GB norm
    eta_charge: float = 0.95
    eta_discharge: float = 0.95
    soc_min_frac: float = 0.05
    soc_max_frac: float = 0.95
    soc_init_frac: float = 0.5

    @property
    def soc_min(self): return self.soc_min_frac * self.energy_mwh

    @property
    def soc_max(self): return self.soc_max_frac * self.energy_mwh

    @property
    def soc_init(self): return self.soc_init_frac * self.energy_mwh


@dataclass
class DispatchConfig:
    dt_hours: float = 0.5
    c_deg_arbitrage: float = 8.0        # GBP per MWh discharged
    c_deg_frequency: float = 4.3        # GBP per MWh of expected FR throughput
    fr_utilisation: float = 0.10        # energy actually moved per MW-h of reserve held
    fr_delivery_hours: float = 0.5      # headroom horizon for constraint (3)
    reserve_headroom: bool = True       # constraint (3) on/off — the experiment switch
    allow_frequency: bool = True
    no_simultaneous: bool = False       # binary; off by default (LP solves faster, rarely binds)
    terminal_soc_frac: float | None = None   # pin end-of-window SOC to avoid horizon gaming
    converter: object | None = None     # ConverterModel; None keeps the flat-efficiency model
    aux_standing_mw: float = 0.0        # thermal management, bought at spot every period


def solve_window(prices: np.ndarray, battery: Battery, cfg: DispatchConfig,
                 fr_prices: np.ndarray | None = None,
                 soc_start: float | None = None) -> dict:
    """Optimise one window. Returns schedule and revenue decomposition."""
    T = len(prices)
    dt = cfg.dt_hours
    soc0 = battery.soc_init if soc_start is None else soc_start
    use_fr = cfg.allow_frequency and fr_prices is not None

    m = pulp.LpProblem("bess_dispatch", pulp.LpMaximize)
    chg = [pulp.LpVariable(f"chg_{t}", 0, battery.power_mw) for t in range(T)]
    dis = [pulp.LpVariable(f"dis_{t}", 0, battery.power_mw) for t in range(T)]
    soc = [pulp.LpVariable(f"soc_{t}", battery.soc_min, battery.soc_max) for t in range(T + 1)]
    res = [pulp.LpVariable(f"res_{t}", 0, battery.power_mw) for t in range(T)] if use_fr \
        else [0.0] * T
    if cfg.no_simultaneous:
        on = [pulp.LpVariable(f"on_{t}", cat="Binary") for t in range(T)]

    # Load-dependent converter loss, entered exactly as the upper envelope of the
    # tangents to a convex loss curve — no binaries, no segment ordering.
    conv = cfg.converter
    if conv is not None:
        tang = conv.tangents(n=12)
        loss_d = [pulp.LpVariable(f"ld_{t}", 0, None) for t in range(T)]
        loss_c = [pulp.LpVariable(f"lc_{t}", 0, None) for t in range(T)]
        for t in range(T):
            for a, b in tang:
                m += loss_d[t] >= a * dis[t] + b
                m += loss_c[t] >= a * chg[t] + b
            # Chord bound. The tangents alone only bound the loss from below, and a
            # lower bound is not always the binding side: during negative prices the
            # program can profit from *overstating* charging loss, because a larger
            # loss leaves room to keep buying while the state of charge is capped.
            # The chord from the origin to rated power is a valid upper bound
            # (P^2/Pr <= P on [0, Pr]) and removes that degree of freedom.
            m += loss_c[t] <= conv.k2 * chg[t]
            m += loss_d[t] <= conv.k2 * dis[t]

    energy_rev = pulp.lpSum((prices[t] * (dis[t] - chg[t]) * dt) for t in range(T))
    if cfg.aux_standing_mw:
        energy_rev -= pulp.lpSum((prices[t] * cfg.aux_standing_mw * dt) for t in range(T))
    fr_rev = pulp.lpSum((fr_prices[t] * res[t] * dt) for t in range(T)) if use_fr else 0
    deg_arb = pulp.lpSum((cfg.c_deg_arbitrage * dis[t] * dt) for t in range(T))
    deg_fr = pulp.lpSum((cfg.c_deg_frequency * res[t] * cfg.fr_utilisation * dt)
                        for t in range(T)) if use_fr else 0
    obj = energy_rev + fr_rev - deg_arb - deg_fr
    if conv is not None:
        # Tie-breaker that pins the loss variables to the lower envelope where the
        # objective is otherwise indifferent to them. Calibrated rather than guessed:
        # sweeping it over 0.5-20 GBP/MWh, the state-of-charge residual falls from
        # 0.21 MWh to 0.003 MWh between 2 and 5, and does not improve above 5, while
        # net revenue moves by 0.01 %. Five is therefore the smallest value that
        # removes the degeneracy without pricing real losses.
        obj -= pulp.lpSum((5.0 * (loss_d[t] + loss_c[t]) * dt) for t in range(T))
    m += obj

    m += soc[0] == soc0
    for t in range(T):
        # (1) energy balance
        if conv is None:
            m += soc[t + 1] == soc[t] + battery.eta_charge * chg[t] * dt - dis[t] * dt / battery.eta_discharge
        else:
            # what leaves the cells is the delivered power plus conversion loss;
            # what reaches the cells is the drawn power minus conversion loss
            m += soc[t + 1] == soc[t] + (chg[t] - loss_c[t]) * dt - (dis[t] + loss_d[t]) * dt
        # (2) power coupling: reserve competes with energy for the same converter
        if use_fr:
            m += dis[t] + res[t] <= battery.power_mw
            m += chg[t] + res[t] <= battery.power_mw
            # (3) deliverability headroom
            if cfg.reserve_headroom:
                m += soc[t] - battery.soc_min >= res[t] * cfg.fr_delivery_hours
                m += battery.soc_max - soc[t] >= res[t] * cfg.fr_delivery_hours
        if cfg.no_simultaneous:
            m += chg[t] <= battery.power_mw * on[t]
            m += dis[t] <= battery.power_mw * (1 - on[t])
    if cfg.terminal_soc_frac is not None:
        m += soc[T] == cfg.terminal_soc_frac * battery.energy_mwh

    status = m.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"solver status: {pulp.LpStatus[status]}")

    v = lambda x: (x.value() if hasattr(x, "value") else float(x)) or 0.0
    chg_v = np.array([v(x) for x in chg])
    dis_v = np.array([v(x) for x in dis])
    res_v = np.array([v(x) for x in res])
    soc_v = np.array([v(x) for x in soc])

    rev_energy = float(np.sum(prices * (dis_v - chg_v) * dt))
    if cfg.aux_standing_mw:
        rev_energy -= float(np.sum(prices * cfg.aux_standing_mw * dt))
    rev_fr = float(np.sum(fr_prices * res_v * dt)) if use_fr else 0.0
    cost_deg = float(cfg.c_deg_arbitrage * np.sum(dis_v) * dt
                     + (cfg.c_deg_frequency * np.sum(res_v) * cfg.fr_utilisation * dt if use_fr else 0.0))
    return {
        "charge_mw": chg_v, "discharge_mw": dis_v, "reserve_mw": res_v, "soc_mwh": soc_v,
        "revenue_energy": rev_energy, "revenue_fr": rev_fr, "cost_degradation": cost_deg,
        "revenue_net": rev_energy + rev_fr - cost_deg,
        "throughput_mwh": float(np.sum(dis_v) * dt),
        "efc": float(np.sum(dis_v) * dt / battery.energy_mwh),
        "soc_end": float(soc_v[-1]),
    }


def run_backtest(df: pd.DataFrame, battery: Battery, cfg: DispatchConfig,
                 price_col: str = "price", fr_col: str | None = None,
                 window_periods: int = 48, forecast: pd.DataFrame | None = None,
                 execute_periods: int | None = None) -> dict:
    """Roll through the series window by window.

    forecast is None            -> perfect foresight (theoretical upper bound)
    forecast supplied           -> optimise on forecast, settle on actuals, and
                                   only the first `execute_periods` of each window
                                   are executed before re-optimising (rolling horizon)
    """
    exec_n = execute_periods or window_periods
    actual = df[price_col].to_numpy(dtype=float)
    fr_actual = df[fr_col].to_numpy(dtype=float) if fr_col else None
    signal = actual if forecast is None else forecast[price_col].to_numpy(dtype=float)
    fr_signal = fr_actual if (forecast is None or fr_col is None) \
        else forecast[fr_col].to_numpy(dtype=float)

    soc = battery.soc_init
    rows, sched = [], []
    for i in range(0, len(actual) - 1, exec_n):
        j = min(i + window_periods, len(actual))
        if j - i < 2:
            break
        r = solve_window(signal[i:j], battery, cfg,
                         fr_prices=(fr_signal[i:j] if fr_col else None), soc_start=soc)
        k = min(exec_n, j - i)
        # settle the executed part against realised prices
        chg, dis, res = r["charge_mw"][:k], r["discharge_mw"][:k], r["reserve_mw"][:k]
        p_act = actual[i:i + k]
        rev_e = float(np.sum(p_act * (dis - chg) * cfg.dt_hours))
        if cfg.aux_standing_mw:
            rev_e -= float(np.sum(p_act * cfg.aux_standing_mw * cfg.dt_hours))
        rev_f = float(np.sum(fr_actual[i:i + k] * res * cfg.dt_hours)) if fr_col else 0.0
        cost = float(cfg.c_deg_arbitrage * np.sum(dis) * cfg.dt_hours
                     + (cfg.c_deg_frequency * np.sum(res) * cfg.fr_utilisation * cfg.dt_hours
                        if fr_col else 0.0))
        soc = float(r["soc_mwh"][k])          # carry realised SOC, not planned end-of-window
        rows.append({"i0": i, "revenue_energy": rev_e, "revenue_fr": rev_f,
                     "cost_degradation": cost, "revenue_net": rev_e + rev_f - cost,
                     "throughput_mwh": float(np.sum(dis) * cfg.dt_hours), "soc_end": soc})
        sched.append(pd.DataFrame({"idx": np.arange(i, i + k), "charge_mw": chg,
                                   "discharge_mw": dis, "reserve_mw": res,
                                   "soc_mwh": r["soc_mwh"][:k], "price": p_act}))

    res_df = pd.DataFrame(rows)
    schedule = pd.concat(sched, ignore_index=True) if sched else pd.DataFrame()
    days = len(actual) * cfg.dt_hours / 24.0
    tot = res_df.revenue_net.sum()
    return {
        "windows": res_df, "schedule": schedule,
        "revenue_energy": float(res_df.revenue_energy.sum()),
        "revenue_fr": float(res_df.revenue_fr.sum()),
        "cost_degradation": float(res_df.cost_degradation.sum()),
        "revenue_net": float(tot),
        "throughput_mwh": float(res_df.throughput_mwh.sum()),
        "efc": float(res_df.throughput_mwh.sum() / battery.energy_mwh),
        "days": days,
        "revenue_per_mw_year": float(tot / battery.power_mw / days * 365.0),
    }


def simulate(schedule_chg: np.ndarray, schedule_dis: np.ndarray, prices: np.ndarray,
             battery: Battery, cfg: DispatchConfig, converter) -> dict:
    """Settle a fixed schedule under the true converter model.

    A schedule optimised on a flat 0.9 efficiency is not generally deliverable once
    load-dependent losses are applied: the energy simply is not there. Rather than
    quietly repairing it, actions are clipped to what the state of charge allows,
    which is what the plant would actually do, and the shortfall shows up as lost
    revenue rather than as an infeasible model.
    """
    dt = cfg.dt_hours
    soc = battery.soc_init
    rev = 0.0
    dis_done = np.zeros_like(schedule_dis)
    chg_done = np.zeros_like(schedule_chg)
    for t in range(len(prices)):
        d, c = float(schedule_dis[t]), float(schedule_chg[t])
        if d > 0:
            avail = max(soc - battery.soc_min, 0.0)
            need = (d + float(converter.loss_mw(d, variable_only=True))) * dt
            if need > avail:
                scale = avail / need if need > 0 else 0.0
                d *= scale
            soc -= (d + float(converter.loss_mw(d, variable_only=True))) * dt if d > 0 else 0.0
        if c > 0:
            room = max(battery.soc_max - soc, 0.0)
            gain = (c - float(converter.loss_mw(c, variable_only=True))) * dt
            if gain > room:
                scale = room / gain if gain > 0 else 0.0
                c *= scale
            soc += (c - float(converter.loss_mw(c, variable_only=True))) * dt if c > 0 else 0.0
        soc = min(max(soc, battery.soc_min), battery.soc_max)
        rev += prices[t] * (d - c) * dt
        if cfg.aux_standing_mw:
            rev -= prices[t] * cfg.aux_standing_mw * dt
        dis_done[t], chg_done[t] = d, c
    deg = cfg.c_deg_arbitrage * float(np.sum(dis_done)) * dt
    return {"revenue_energy": float(rev), "cost_degradation": deg,
            "revenue_net": float(rev - deg),
            "throughput_mwh": float(np.sum(dis_done) * dt),
            "delivered_fraction": float(np.sum(dis_done) / max(np.sum(schedule_dis), 1e-9))}
