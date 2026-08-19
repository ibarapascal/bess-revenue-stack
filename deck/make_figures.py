"""
Build the deck figures from ../results/ only. Nothing is recomputed here.

Run:     python deck/make_figures.py      (from the repository root)
Output:  deck/fig/*.png at 300 dpi

Colour meaning (report-deck convention):
    blue  = measured fact
    red   = what the reader should look at (loss, overstatement, own estimate)
    grey  = context
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import palette as P

HERE = Path(__file__).parent
RES = HERE.parent / "results"
FIG = HERE / "fig"
FIG.mkdir(exist_ok=True)
plt.style.use(str(HERE / "deck.mplstyle"))

# Figure sizes matched to the body area (750x352pt / 750x302pt)
FULL = (10.42, 4.89)
FULL_RO = (10.42, 4.25)
HALF = (7.0, 4.25)


def annot(ax, text, xy, xytext, color=P.RED_ALERT, fs=10.5, ha="center", arrow=True):
    ax.annotate(text, xy=xy, xytext=xytext, ha=ha, fontsize=fs, fontweight="bold",
                color=P.WHITE,
                bbox=dict(boxstyle="square,pad=0.35", facecolor=color, edgecolor="none"),
                arrowprops=dict(arrowstyle="-", color=color, lw=1.2,
                                linestyle=(0, (3, 2))) if arrow else None, zorder=10)


def save(fig, name):
    fig.savefig(FIG / f"{name}.png")
    plt.close(fig)
    print(f"  {name}")


# --- 1. Waterfall: what a perfect-foresight number hides --------------------
def fig_waterfall():
    d = pd.read_csv(RES / "v2_capture_rate.csv").set_index("arm")
    pf = d.loc["perfect foresight", "gross_GBP"]
    gbm_gross = d.loc["gbm", "gross_GBP"]
    gbm_net = d.loc["gbm", "net_GBP"]
    fc_err = pf - gbm_gross
    deg = gbm_gross - gbm_net

    fig, ax = plt.subplots(figsize=FULL_RO)
    x = np.arange(4)
    ax.bar(0, pf / 1e6, color=P.BLUE_PRIMARY, width=0.62)
    ax.bar(1, fc_err / 1e6, bottom=gbm_gross / 1e6, color=P.RED_ALERT, width=0.62)
    ax.bar(2, deg / 1e6, bottom=gbm_net / 1e6, color=P.RED_ALERT, width=0.62)
    ax.bar(3, gbm_net / 1e6, color=P.BLUE_DEEP, width=0.62)
    for xi, (v, lab) in enumerate([(pf, f"£{pf/1e6:.2f}m"), (fc_err, f"−£{fc_err/1e6:.2f}m"),
                                   (deg, f"−£{deg/1e6:.2f}m"), (gbm_net, f"£{gbm_net/1e6:.2f}m")]):
        top = {0: pf, 1: pf, 2: gbm_gross, 3: gbm_net}[xi] / 1e6
        ax.text(xi, top + 0.09, lab, ha="center", fontsize=13, fontweight="bold",
                color=P.RED_ALERT if xi in (1, 2) else P.BLUE_DEEP)
    for xi in (0, 1, 2):
        y = {0: gbm_gross, 1: gbm_net, 2: gbm_net}[xi] / 1e6
        ax.plot([xi + 0.31, xi + 1 - 0.31], [y, y], color=P.GRAY_LINE, lw=1, ls="--")
    ax.set_xticks(x)
    ax.set_xticklabels(["perfect-foresight\ngross margin", "− forecast error",
                        "− degradation cost", "achievable\nnet revenue"])
    ax.set_ylabel("£m over the 22 months to Jan 2026")
    ax.set_ylim(0, 4.6)
    annot(ax, "a factor of 2.8 between the two ends\n4.1 at the German wear price",
          (3, gbm_net / 1e6 + 0.1), (1.45, 0.75))
    fig.tight_layout(pad=0.4)
    save(fig, "waterfall")


# --- 2. The wear price is a four-input calculation --------------------------
def fig_cdeg():
    d = pd.read_csv(RES / "v0_cdeg_inputs.csv")
    d = d[~d.variant.str.startswith("convention")]
    used = d.variant.str.contains(r"\(used\)")
    fig, axes = plt.subplots(1, 2, figsize=FULL_RO, gridspec_kw={"width_ratios": [1.55, 1]})
    ax = axes[0]
    lbl = [v.replace(" (used)", "") for v in d.variant]
    y = np.arange(len(d))[::-1]
    ax.barh(y, d.c_deg, height=0.62,
            color=[P.RED_ALERT if u else P.BLUE_LIGHT for u in used])
    for yi, (v, u) in zip(y, zip(d.c_deg, used)):
        ax.text(v + 0.5, yi, f"{v:.1f}", va="center", fontsize=10,
                fontweight="bold", color=P.RED_ALERT if u else P.GRAY_DARK)
    ax.set_yticks(y)
    ax.set_yticklabels(lbl, fontsize=10)
    ax.set_xlabel("cost of wear, £/MWh throughput")
    ax.set_xlim(0, 34)
    ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    ax.set_title("only one of the four inputs is measured", fontsize=11.5, loc="left",
                 fontweight="bold", color=P.GRAY_DARK)

    b = pd.read_csv(RES / "v2_cdeg_band.csv")
    ax = axes[1]
    names = ["field-anchored\n£12.1/MWh", "German 8-yr record\n£20.2/MWh"]
    ax.bar(names, b.overstatement_factor, color=[P.BLUE_PRIMARY, P.RED_ALERT], width=0.5)
    for xi, v in enumerate(b.overstatement_factor):
        ax.text(xi, v + 0.09, f"×{v:.2f}", ha="center", fontsize=14, fontweight="bold",
                color=P.BLUE_PRIMARY if xi == 0 else P.RED_ALERT)
    ax.set_ylabel("perfect-foresight gross ÷ achievable net")
    ax.set_ylim(0, 4.8)
    ax.set_title("what the wear price does to the headline", fontsize=11.5, loc="left",
                 fontweight="bold", color=P.GRAY_DARK)
    fig.tight_layout(pad=0.5)
    save(fig, "cdeg")


# --- 3. Reserve sold without state-of-charge headroom -----------------------
def fig_headroom():
    d = pd.read_csv(RES / "v1_reserve_headroom.csv")
    fig, axes = plt.subplots(1, 2, figsize=FULL_RO)
    ax = axes[0]
    x = np.arange(len(d))
    ax.bar(x - 0.19, d.mean_reserve_MW_without, width=0.36, color=P.RED_ALERT,
           label="committed without the constraint")
    ax.bar(x + 0.19, d.mean_reserve_MW_with, width=0.36, color=P.BLUE_PRIMARY,
           label="deliverable with it")
    ax.set_xticks(x)
    ax.set_xticklabels([f"£{p:.0f}" for p in d.fr_price_GBP_per_MW_h])
    ax.set_xlabel("reserve price, £/MW/h")
    ax.set_ylabel("mean reserve position, MW")
    ax.legend(loc="lower center", ncol=1, fontsize=10, frameon=False,
              bbox_to_anchor=(0.5, -0.42))
    annot(ax, "40.1 MW sold, 26.5 MW deliverable", (0, 40.1), (1.35, 47))
    ax.set_ylim(0, 56)

    ax = axes[1]
    ax.plot(d.fr_price_GBP_per_MW_h, d.overstatement_pct, color=P.RED_ALERT,
            marker="o", lw=2.2)
    for xp, yp in zip(d.fr_price_GBP_per_MW_h, d.overstatement_pct):
        ax.text(xp, yp + 0.7, f"{yp:.1f}%", ha="center", fontsize=10.5, fontweight="bold",
                color=P.RED_ALERT)
    ax.set_xlabel("reserve price, £/MW/h")
    ax.set_ylabel("overstatement of net revenue, %")
    ax.set_ylim(0, 18)
    ax.set_title("the error shrinks as the price rises — the battery would have\n"
                 "held that headroom anyway", fontsize=10.5, loc="left", color=P.GRAY_DARK)
    fig.tight_layout(pad=0.5)
    save(fig, "headroom")


# --- 4. What a real forecast captures ---------------------------------------
def fig_capture():
    d = pd.read_csv(RES / "v2_capture_rate.csv")
    d = d[d.arm != "perfect foresight"]
    fig, ax = plt.subplots(figsize=HALF)
    x = np.arange(len(d))
    ax.bar(x - 0.2, d.capture_gross_pct, width=0.38, color=P.BLUE_PRIMARY,
           label="of gross margin")
    ax.bar(x + 0.2, d.capture_net_pct, width=0.38, color=P.RED_ALERT,
           label="of net revenue")
    for xi, (g, n) in enumerate(zip(d.capture_gross_pct, d.capture_net_pct)):
        ax.text(xi - 0.2, g + 1.4, f"{g:.0f}%", ha="center", fontsize=12, fontweight="bold",
                color=P.BLUE_PRIMARY)
        ax.text(xi + 0.2, n + 1.4, f"{n:.0f}%", ha="center", fontsize=12, fontweight="bold",
                color=P.RED_ALERT)
    ax.set_xticks(x)
    ax.set_xticklabels(["persistence\n(yesterday's shape)", "gradient boosting\non lagged prices"])
    ax.set_ylabel("captured, % of perfect foresight")
    ax.set_ylim(0, 78)
    ax.legend(loc="upper center", ncol=2, fontsize=10, frameon=False,
              bbox_to_anchor=(0.5, 1.13))
    fig.tight_layout(pad=0.4)
    save(fig, "capture")


# --- 5. The flat efficiency assumption: two errors that cancel --------------
def fig_efficiency():
    v3 = pd.read_csv(RES / "v3_converter_efficiency.csv")
    v6 = pd.read_csv(RES / "v6_duration.csv")
    fig, axes = plt.subplots(1, 2, figsize=FULL_RO)
    ax = axes[0]
    ax.plot(v3.hvac_MW, v3.overstatement_pct, color=P.RED_ALERT, marker="o", lw=2.2)
    ax.axhline(0, color=P.GRAY_DARK, lw=0.9)
    ax.set_xlabel("thermal management load, MW")
    ax.set_ylabel("overstatement of net revenue, %")
    annot(ax, "with no thermal load the flat assumption\nis 2.9% LOW, not high",
          (0.0, -2.9), (0.085, -1.2))
    ax.set_title("the sign depends entirely on the auxiliary load",
                 fontsize=11, loc="left", fontweight="bold", color=P.GRAY_DARK)

    ax = axes[1]
    x = np.arange(len(v6))
    lev = v6.level_effect_GBP / 1e3
    sha = v6.shape_effect_GBP / 1e3
    ax.bar(x, lev, width=0.5, color=P.BLUE_PRIMARY, label="level error (average efficiency)")
    ax.bar(x, sha, bottom=lev, width=0.5, color=P.RED_ALERT, label="shape error (load dependence)")
    for xi, (l, s) in enumerate(zip(lev, sha)):
        ax.text(xi, l + s + 12, f"{s/(l+s)*100:.1f}% is shape", ha="center",
                fontsize=10.5, fontweight="bold", color=P.RED_ALERT)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{h:.0f} h" for h in v6.duration_h])
    ax.set_ylabel("efficiency-curve term, £k")
    ax.set_ylim(0, 560)
    ax.legend(loc="upper left", fontsize=10, frameon=False)
    ax.set_title("tested at 1, 2 and 4 hours", fontsize=11, loc="left",
                 fontweight="bold", color=P.GRAY_DARK)
    fig.tight_layout(pad=0.5)
    save(fig, "efficiency")


# --- 6. One wear price for every service ------------------------------------
def fig_service():
    d = pd.read_csv(RES / "v4_service_cdeg.csv")
    d = d[d.fr_price == 2.0]
    fig, axes = plt.subplots(1, 2, figsize=HALF)
    ax = axes[0]
    ax.plot(d.ageing_ratio, d.mean_reserve_MW, color=P.BLUE_PRIMARY, marker="o", lw=2.2)
    ax.set_xlabel("ageing ratio, arbitrage ÷ frequency")
    ax.set_ylabel("mean reserve position, MW")
    ax.set_title("more reserve is held", fontsize=11, loc="left", color=P.GRAY_DARK)
    ax = axes[1]
    base = d[d.ageing_ratio == 1.0].net_GBP.iloc[0]
    ax.plot(d.ageing_ratio, (d.net_GBP / base - 1) * 100, color=P.RED_ALERT,
            marker="o", lw=2.2)
    for xp, yp in zip(d.ageing_ratio, (d.net_GBP / base - 1) * 100):
        ax.text(xp, yp + 0.16, f"{yp:+.1f}%", ha="center", fontsize=10.5,
                fontweight="bold", color=P.RED_ALERT)
    ax.set_xlabel("ageing ratio, arbitrage ÷ frequency")
    ax.set_ylabel("net revenue vs one flat price, %")
    ax.set_title("and net revenue rises", fontsize=11, loc="left", color=P.GRAY_DARK)
    fig.tight_layout(pad=0.5)
    save(fig, "service")


# --- 7. How much of this is the sample --------------------------------------
def fig_bootstrap():
    d = pd.read_csv(RES / "v7_bootstrap.csv")
    keep = ["deg overstatement, italian c_deg", "deg overstatement, german c_deg",
            "headroom overstatement @ GBP2/MW/h", "headroom overstatement @ GBP10/MW/h",
            "conventional overstatement, no thermal", "shape share of the efficiency term",
            "service-differentiation gain @ GBP5/MW/h",
            "gross capture, gbm", "net capture, gbm"]
    lbl = ["degradation, field-anchored price", "degradation, German price",
           "reserve headroom @ £2/MW/h", "reserve headroom @ £10/MW/h",
           "flat efficiency, no thermal load", "shape share of the efficiency term",
           "service-differentiated wear @ £5/MW/h",
           "capture of gross margin (GBM)", "capture of net revenue (GBM)"]
    d = d.set_index("quantity").loc[keep].reset_index()
    y = np.arange(len(d))[::-1]
    fig, ax = plt.subplots(figsize=FULL_RO)
    colors = [P.RED_ALERT if "capture" not in l else P.BLUE_PRIMARY for l in lbl]
    ax.errorbar(d.point, y, xerr=[d.point - d.ci95_lo, d.ci95_hi - d.point],
                fmt="none", ecolor=P.GRAY_DARK, elinewidth=1.4, capsize=4, zorder=1)
    ax.scatter(d.point, y, s=54, c=colors, zorder=2)
    for yi, (pt, lo, hi) in zip(y, zip(d.point, d.ci95_lo, d.ci95_hi)):
        ax.text(hi + 1.6, yi, f"{pt:.1f}  [{lo:.1f}, {hi:.1f}]", va="center",
                fontsize=10, color=P.GRAY_DARK)
    ax.axvline(0, color=P.GRAY_DARK, lw=0.9)
    ax.set_yticks(y)
    ax.set_yticklabels(lbl, fontsize=10.5)
    ax.set_xlabel("effect size, % (point estimate and 95% moving-block bootstrap interval)")
    ax.set_xlim(-12, 118)
    ax.grid(axis="x"); ax.grid(axis="y", visible=False)
    fig.tight_layout(pad=0.4)
    save(fig, "bootstrap")


if __name__ == "__main__":
    print("generating figures ->", FIG)
    for fn in [fig_waterfall, fig_cdeg, fig_headroom, fig_capture,
               fig_efficiency, fig_service, fig_bootstrap]:
        fn()
    print("done")
