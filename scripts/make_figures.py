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
    ax.set_ylabel("£ over 2024–2025")
    ax.set_title("What a perfect-foresight number hides\n50 MW / 100 MWh, GB wholesale",
                 fontsize=9.5)
    fig.tight_layout(); fig.savefig(FIG / "waterfall.png"); plt.close(fig)
    print("figures/waterfall.png")


def fig_transmission():
    """Forecast error to revenue is strongly non-linear."""
    t = pd.read_csv(RES / "v2_transmission.csv").sort_values("mae")
    fig, ax = plt.subplots(figsize=(5.4, 3.4))
    ax.plot(t.mae, t.capture_net_pct, "o-", color="#4878a8", label="net revenue")
    if "capture_gross_pct" in t:
        ax.plot(t.mae, t.capture_gross_pct, "s--", color="#8172b2", label="gross margin")
    ax.invert_xaxis()
    ax.set_xlabel("forecast MAE (£/MWh)  — better to the right")
    ax.set_ylabel("% of perfect-foresight revenue")
    ax.set_title("Forecast skill buys revenue non-linearly", fontsize=9.5)
    ax.legend(fontsize=8)
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
    ax.set_ylabel("net revenue over Q1 2025 (£k)")
    ax2.set_ylabel("equivalent full cycles / yr")
    ax.set_title("Pricing degradation changes revenue and behaviour", fontsize=9.5)
    h1, l1 = ax.get_legend_handles_labels(); h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, fontsize=8, loc="upper right")
    fig.tight_layout(); fig.savefig(FIG / "degradation.png"); plt.close(fig)
    print("figures/degradation.png")


if __name__ == "__main__":
    fig_degradation()
    fig_waterfall()
    fig_transmission()
