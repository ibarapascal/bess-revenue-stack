"""Figures for the README. One chart per finding, no decoration."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RES, FIG = ROOT / "results", ROOT / "figures"
FIG.mkdir(exist_ok=True)
plt.rcParams.update({"figure.dpi": 160, "font.size": 9, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.spines.top": False, "axes.spines.right": False})


def fig_waterfall():
    """Where perfect-foresight revenue goes once the model stops cheating."""
    v2 = json.loads((RES / "v2_capture_rate.json").read_text())
    arms = {a["arm"]: a for a in v2["arms"]}
    pf, gbm = arms["perfect foresight"], arms["gbm"]
    steps = [("perfect foresight\ngross margin", pf["gross_GBP"], "#4878a8"),
             ("− forecast error", -(pf["gross_GBP"] - gbm["gross_GBP"]), "#c44e52"),
             ("− degradation cost", -gbm["deg_cost_GBP"], "#c44e52"),
             ("achievable\nnet revenue", gbm["net_GBP"], "#55a868")]
    fig, ax = plt.subplots(figsize=(6.2, 3.6))
    run = 0.0
    for i, (label, val, colour) in enumerate(steps):
        if i == 0:                      # opening level
            ax.bar(i, val, color=colour, width=0.6)
            ax.text(i, val, f"£{val/1e6:.2f}m", ha="center", va="bottom", fontsize=8)
            run = val
        elif i == len(steps) - 1:       # closing level
            ax.bar(i, val, color=colour, width=0.6)
            ax.text(i, val, f"£{val/1e6:.2f}m", ha="center", va="bottom", fontsize=8)
        else:                           # decrement: bar hangs from run down to run+val
            ax.bar(i, abs(val), bottom=run + val, color=colour, width=0.6)
            ax.text(i, run + val / 2, f"−£{abs(val)/1e6:.2f}m", ha="center", va="center",
                    fontsize=8, color="white")
            ax.plot([i - 0.3, i + 0.3], [run, run], color="0.4", lw=0.7, zorder=3)
            run += val
    ax.set_ylim(0, steps[0][1] * 1.15)
    ax.set_xticks(range(len(steps)))
    ax.set_xticklabels([s[0] for s in steps], fontsize=8)
    ax.set_ylabel("£ over the 22 months to Jan 2026")
    ax.set_title("What a perfect-foresight number hides\n50 MW / 100 MWh, GB wholesale",
                 fontsize=9.5)
    fig.tight_layout(); fig.savefig(FIG / "waterfall.png"); plt.close(fig)
    print("figures/waterfall.png")


def fig_transmission():
    """The same runs on two skill axes. Which axis is used decides how non-linear the
    relationship looks, so both are drawn rather than the flattering one."""
    t = pd.read_csv(RES / "v2_transmission.csv").sort_values("mae")
    has_rho = "within_day_rank_corr" in t
    fig, axes = plt.subplots(1, 2 if has_rho else 1, figsize=(8.4 if has_rho else 5.4, 3.5),
                             squeeze=False)
    ax = axes[0][0]
    ax.plot(t.mae, t.capture_net_pct, "o-", color="#4878a8", label="net revenue")
    if "capture_gross_pct" in t:
        ax.plot(t.mae, t.capture_gross_pct, "s--", color="#8172b2", label="gross margin")
    ax.invert_xaxis()
    ax.set_xlabel("forecast MAE (£/MWh) — better to the right")
    ax.set_ylabel("% of perfect-foresight revenue")
    ax.set_title("on an error axis: looks strongly non-linear", fontsize=9)
    ax.legend(fontsize=8)

    if has_rho:
        ax2 = axes[0][1]
        r = t.sort_values("within_day_rank_corr")
        ax2.plot(r.within_day_rank_corr, r.capture_net_pct, "o-", color="#4878a8",
                 label="net revenue")
        # straight line between the endpoints, so departure from linearity is visible
        # rather than asserted
        ax2.plot([r.within_day_rank_corr.iloc[0], r.within_day_rank_corr.iloc[-1]],
                 [r.capture_net_pct.iloc[0], r.capture_net_pct.iloc[-1]],
                 ":", color="0.5", lw=1.0, label="straight line for reference")
        ax2.set_xlabel("within-day rank correlation — better to the right")
        ax2.set_title("on an ordering axis: close to linear", fontsize=9)
        ax2.legend(fontsize=8)
    fig.suptitle("What forecast skill buys depends on how skill is measured", fontsize=9.5)
    fig.tight_layout(); fig.savefig(FIG / "transmission.png"); plt.close(fig)
    print("figures/transmission.png")


def fig_degradation():
    """Degradation cost changes both revenue and behaviour."""
    v0 = pd.read_csv(RES / "v0_arbitrage.csv")
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    x = range(len(v0))
    ax.bar([i - 0.2 for i in x], v0.net_GBP / 1e3, width=0.4, color="#4878a8", label="net revenue (£k)")
    ax2 = ax.twinx()
    ax2.bar([i + 0.2 for i in x], v0.efc_per_year, width=0.4, color="#dd8452", label="cycles/yr")
    ax2.grid(False)
    ax.set_xticks(list(x))
    ax.set_xticklabels([s.replace(" field-anchored", "\nfield-anchored").replace(
        "no degradation cost", "ignored") for s in v0.scenario], fontsize=7.5)
    ax.set_ylabel("net revenue, Mar 2024 – Jan 2026 (£k)")
    ax2.set_ylabel("equivalent full cycles / yr")
    ax.set_title("Pricing degradation changes revenue and behaviour", fontsize=9.5)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper right")
    fig.tight_layout(); fig.savefig(FIG / "degradation.png"); plt.close(fig)
    print("figures/degradation.png")


def fig_efficiency_error():
    """The two errors in a flat-efficiency assumption point in opposite directions."""
    v3 = pd.read_csv(RES / "v3_converter_efficiency.csv").sort_values("hvac_MW")
    x = range(len(v3))
    fig, ax = plt.subplots(figsize=(6.0, 3.6))
    ax.bar([i - 0.19 for i in x], v3.error_from_aux_GBP / 1e3, width=0.38,
           color="#c44e52", label="omitted auxiliary load")
    ax.bar([i + 0.19 for i in x], v3.error_from_curve_shape_GBP / 1e3, width=0.38,
           color="#4878a8", label="assumed flat efficiency")
    ax.axhline(0, color="0.3", lw=0.8)
    ax2 = ax.twinx()
    ax2.plot(list(x), v3.overstatement_pct, "o-", color="#55a868", lw=1.4,
             label="net overstatement (%)")
    ax2.grid(False)
    # Pin the two zeros to the same height. Without this the line appears to cross
    # zero at a different place from the bars, which is exactly the wrong thing to
    # misread on a chart whose whole point is a sign change.
    y0, y1 = ax.get_ylim()
    frac = -y0 / (y1 - y0)
    top = float(v3.overstatement_pct.max()) * 1.15
    ax2.set_ylim(-frac / (1 - frac) * top, top)
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"{h:.2f}" for h in v3.hvac_MW])
    ax.set_xlabel("standing thermal load (MW)")
    ax.set_ylabel("error in reported net revenue (£k, Mar 2024 – Jan 2026)")
    ax2.set_ylabel("net overstatement (%)")
    ax.set_title("A flat efficiency assumption errs in both directions at once\n"
                 "positive overstates revenue, negative understates it", fontsize=9.5)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper left")
    fig.tight_layout(); fig.savefig(FIG / "efficiency_error.png"); plt.close(fig)
    print("figures/efficiency_error.png")


def fig_service_cdeg():
    """What pricing wear by service changes about reserve participation."""
    v4 = pd.read_csv(RES / "v4_service_cdeg.csv")
    flat = v4[v4.ageing_ratio == 1.0].sort_values("fr_price")
    diff = v4[v4.ageing_ratio == 1.85].sort_values("fr_price")
    x = range(len(flat))
    fig, ax = plt.subplots(figsize=(5.6, 3.5))
    ax.bar([i - 0.19 for i in x], flat.mean_reserve_MW, width=0.38,
           color="#8172b2", label="one degradation cost for all energy")
    ax.bar([i + 0.19 for i in x], diff.mean_reserve_MW, width=0.38,
           color="#dd8452", label="wear priced by service (1.85×)")
    # Annotate the outright-refusal case only when the data actually shows one. This
    # text was once unconditional, and after a recalibration moved the single-cost bar
    # from 0.0 to 20.3 MW the figure kept asserting a refusal that no longer existed.
    if float(flat.mean_reserve_MW.iloc[0]) < 0.5:
        ax.annotate("declines the\nmarket entirely", xy=(-0.19, 0.4), xytext=(-0.30, 14),
                    fontsize=7.5, ha="center", color="#8172b2",
                    arrowprops=dict(arrowstyle="->", color="#8172b2", lw=0.8))
    ax.set_xticks(list(x))
    ax.set_xticklabels([f"£{p:.0f}" for p in flat.fr_price])
    ax.set_xlabel("reserve availability price (£/MW/h)")
    ax.set_ylabel("mean reserve held (MW of 50)")
    # The title must not outrun the data: at the current wear price both models
    # participate, and only at a high enough wear price does participation itself flip.
    flips = float(flat.mean_reserve_MW.iloc[0]) < 0.5
    ax.set_title("Whether the battery enters the reserve market at all\n"
                 "depends on how its wear is priced" if flips else
                 "Pricing reserve wear at its measured lower ageing\n"
                 "shifts capacity toward reserve and cuts cycling", fontsize=9.5)
    ax.legend(fontsize=8, loc="upper left")
    fig.tight_layout(); fig.savefig(FIG / "service_cdeg.png"); plt.close(fig)
    print("figures/service_cdeg.png")


if __name__ == "__main__":
    fig_degradation()
    fig_waterfall()
    fig_transmission()
    fig_efficiency_error()
    fig_service_cdeg()
