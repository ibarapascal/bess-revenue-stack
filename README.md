# BESS revenue stack — what published battery revenue models get wrong, quantified

Grid-scale battery revenue models are easy to write and easy to get wrong in ways
that do not announce themselves. The model still solves. The dispatch schedule
still looks reasonable. The revenue number is simply too high, and nothing in the
output says so.

This project measures how much too high, one modelling shortcut at a time, on real
GB market data with a battery degradation cost anchored to observed field data.
The backtester exists to produce those numbers; the numbers are the point.

![waterfall](figures/waterfall.png)

Of £3.15m of perfect-foresight gross margin over 2024–2025 for a 50 MW / 100 MWh
battery, forecast error removes £1.49m and degradation cost removes a further
£1.28m. What is left, £0.38m, is what the asset could actually have earned. A model
that reports the first number and calls it revenue is wrong by a factor of eight.

## Findings so far

All figures below: 50 MW / 100 MWh battery, GB wholesale (Elexon MID/APXMIDP),
Q1 2025, perfect foresight. Perfect foresight is a theoretical upper bound and is
never achievable — it is used here because these are *relative* comparisons where
both arms share the same advantage.

**1. Ignoring degradation cost overstates arbitrage revenue by 60–102 % and implies
cycling no owner would accept.**

A degradation cost cannot be set from an annual loss rate alone: the same 2 %/yr means
a very different cost per MWh depending on how hard the asset was cycled to get there.
Only one public field case reports both — an Italian utility-scale plant, 356
equivalent full cycles over three years to 95.9 % state of health, so 119 EFC/yr at
1.37 %/yr. The other field cases give a rate without a cycle count and enter as
sensitivity under an assumed 300 EFC/yr, labelled as such rather than as calibration.

| degradation assumption | c_deg (£/MWh) | net revenue (£) | £/MW/yr | cycles/yr |
|---|---|---|---|---|
| ignored, as in many public models | 0 | 653,902 | 53,026 | 637 |
| Italian field pair (1.37 %/yr at 119 EFC) | 30.6 | 324,101 | 26,282 | 284 |
| EPRI 2.3 %/yr, EFC assumed 300 | 20.3 | 408,535 | 33,129 | 379 |
| German upper 3 %/yr, EFC assumed 300 | 26.5 | 354,726 | 28,766 | 323 |

637 equivalent full cycles per year is close to two a day. Pricing the wear cuts
cycling by 41–55 % and removes 60–102 % of the revenue, and the only fully
field-derived row is the most severe of the three.

**2. Omitting the state-of-charge headroom constraint overstates net revenue by
2–12 %, by selling reserve the battery could not have delivered.**

A battery paid an availability fee for reserve must hold enough energy to actually
deliver it:

```
SOC(t) − SOC_min ≥ R(t) · T_delivery      (deliver upward)
SOC_max − SOC(t) ≥ R(t) · T_delivery      (absorb downward)
```

Without these, the same stored energy is sold twice — once as arbitrage, once as
availability.

| reserve price (£/MW/h) | net with constraint | net without | overstated by | mean reserve held (MW) |
|---|---|---|---|---|
| 2 | 337,708 | 356,655 | 5.6 % | 22.0 → 43.4 |
| 5 | 577,253 | 643,620 | 11.5 % | 43.1 → 45.0 |
| 10 | 1,068,088 | 1,135,481 | 6.3 % | 46.9 → 46.1 |
| 20 | 2,106,331 | 2,153,744 | 2.3 % | 48.8 → 48.1 |

The revenue error is worst when reserve is cheap enough that the battery must genuinely
choose between markets. At £2/MW/h the model without the constraint commits almost
twice the reserve it can back with energy — 43.4 MW against a deliverable 22.0 MW.

**3. A day-ahead forecast captures 53 % of perfect-foresight gross margin but only
21 % of net revenue — degradation cost amplifies forecast error rather than scaling
with it.**

| arm | forecast MAE (£/MWh) | gross margin | net revenue | net capture |
|---|---|---|---|---|
| perfect foresight | 0 | 3,145,765 | 1,781,029 | 100 % |
| LightGBM day-ahead | 20.1 | 1,656,585 (52.7 %) | 380,743 | 21.4 % |
| naive (yesterday, same period) | 21.2 | 1,508,628 (48.0 %) | 145,640 | 8.2 % |

The gap between the gross and net columns is the finding. A battery pays for its own
wear on every cycle whether or not the trade was profitable, so an imperfect forecast
loses margin twice: once in the trade, and again in the wear spent chasing it. The
effect strengthens as the degradation cost rises, which is why the field-derived
c_deg of £30.6/MWh leaves a thinner net margin for error to eat than a nominal £15
would.

![transmission](figures/transmission.png)

The transmission from forecast skill to revenue is strongly non-linear. Cutting MAE by
a quarter, from £20.1 to £15.1/MWh, triples net capture from 21 % to 61 %; the
remaining three quarters of the improvement buy the last 39 points. For an operator
this reverses the usual intuition about where effort is worth spending.

*Scope*: this applies to a strategy priced off the half-hourly reference price, which
is not known in advance. It does not apply to day-ahead auction arbitrage, where the
clearing price is known at gate closure and perfect foresight is close to achievable
for that leg. The forecast-dependent part of a real revenue stack is within-day and
balancing.

**4. Of everything a conventional efficiency assumption gets wrong, the expensive part
is not the efficiency curve — it is the auxiliary load nobody models.**

Converter loss has a load-independent part and a part growing with the square of
current, so efficiency peaks near half load and falls at both ends. Calibrated to field
measurement of a utility-scale plant (85 % round trip at rated, 65 % at 10 % load):

| load | 5 % | 10 % | 25 % | 50 % | 75 % | 100 % |
|---|---|---|---|---|---|---|
| round-trip efficiency | 0.46 | 0.65 | 0.81 | 0.86 | 0.86 | 0.85 |

Four arms, each isolating one omission (H1 2025, thermal load 0 to 0.2 MW):

| arm | net revenue | |
|---|---|---|
| conventional: flat 0.9, no auxiliary draw | 624,632 | what a typical model prints |
| the same schedule, paying auxiliaries | 484,275–559,444 | 79–89 % of the total gap |
| the same schedule, also settled on the real curve | 467,095–542,263 | the remaining 11–21 % |
| optimised with the curve inside the program | 482,030–557,198 | recovers 2.8–3.2 % |

The conventional number is overstated by 15 % with no thermal load at all and 34 % at
0.2 MW, and four fifths to nine tenths of that error is auxiliary consumption rather
than the shape of the efficiency curve. Modelling the curve is worth under 3 % and
leaves dispatch essentially unchanged: mean discharge load moves from 86.3 % to 86.2 %
of rated power. Charging the converter's no-load loss per active period rewards running
hard for fewer periods, which cancels the pull toward the mid-load efficiency peak.

The expensive omission is therefore the one that sounds boring. This is also the finding
the project got most wrong before checking it — see Verification below.

**5. Pricing wear by service decides whether the battery enters the reserve market at
all — not just what it books.**

Module tests under real grid duty profiles put peak-shifting ageing at 1.81–1.92×
frequency regulation at comparable throughput. Carrying that distinction, rather than
one degradation cost for all energy:

| reserve price (£/MW/h) | mean reserve held, one cost | with 1.85× ratio | cycling | net |
|---|---|---|---|---|
| 2 | 0.00 MW | 22.13 MW | −4.5 % | +4.3 % |
| 5 | 37.95 MW | 41.89 MW | −18.1 % | +28.0 % |
| 10 | 46.25 MW | 46.74 MW | −8.3 % | +15.6 % |

At £2/MW/h the single-cost model declines the reserve market outright — it holds no
reserve at all, because one degradation cost makes the availability payment look
uneconomic. The differentiated model commits 22 MW, because reserve duty is gentler on
the cells than arbitrage duty. That is a binary difference in whether the asset
participates, which no percentage change captures. Where both models participate the
capacity shift is modest, but cycling falls 4–18 % and net revenue rises 4–28 %
throughout.

This finding rests on the weakest assumption in the project, and it is stated in the
code: mapping a capacity-loss ratio onto a marginal-cost ratio presumes damage
accumulates linearly with throughput, which is the approximation degradation physics is
known to violate. The ratio is therefore swept from 1.0 to 2.5 rather than asserted.

## What is different here

**Degradation level comes from the field as a pair, shape comes from the cell.** Public
cell-level ageing models (NREL BLAST-Lite, parameterised on Naumann et al. and on NREL's
own large-format prismatic tests) predict 5–7 %/yr capacity loss at 300 equivalent full
cycles, against measured whole-system loss of 1.4–3 %/yr. Running them unscaled prices
degradation above realistic spreads and silently shuts off all trading, so the cell model
supplies the *response* to depth, rate and temperature while field evidence supplies the
*level*. The anchoring needs both a loss rate and the cycling that produced it, which
only one public case reports: the Italian plant's 119 EFC/yr at 1.37 %/yr. Anchoring
instead to the model's own cycling — a fixed point in EFC — was considered and rejected,
because it assumes this asset cycles at the same rate as the field systems, which is
exactly what is unknown; that choice moves c_deg from £30.6 to £10.9/MWh, so it is stated
rather than buried.

**Auxiliary consumption is separated by where it actually arises.** The converter's
no-load loss (1.17 MW, 2.3 % of rated) is charged only in periods when the converter
runs, gated by one binary per period; thermal management is the genuinely
round-the-clock part and is swept over 0–0.2 MW, an order of magnitude taken from the
1–3 % of throughput that field data supports rather than picked for effect.

**Degradation cost is differentiated by service.** Module tests on 220 Ah LFP under
real grid duty profiles put peak-shifting ageing at 1.81–1.92× frequency regulation
at equal throughput. That ratio is carried into the optimiser so that arbitrage and
reserve are not priced identically. The assumption this rests on — that damage is
proportional to throughput, i.e. linear accumulation — is exactly the approximation
degradation physics is known to violate, and is flagged in the code rather than
buried.

**No API keys, no manual downloads.** The Elexon Insights endpoints used here are
open (verified 2026-07-28); existing Python wrappers for them are unmaintained, so
the client is self-contained and caches to parquet. One command reproduces every
number above from nothing.

## Verification

`scripts/verify.py` asserts the invariants that a plausible-looking model can still
violate. Every check exists because something went wrong once:

- state of charge is the exact integral of what crossed the terminals, under both the
  flat and the load-dependent loss model
- reserve is always deliverable when the headroom constraint is on, and demonstrably
  undeliverable when it is off, so the experiment measures what it claims to
- the tangent representation of converter loss reproduces the analytic curve to 0.01 %
  of rated power
- field anchoring reproduces the degradation rate it targets, to machine precision
- no forecast feature at time t responds to a price at t or later, verified by
  perturbing a future price and confirming that no earlier feature row moves

The suite earned its place immediately, and then a full review of the repository
earned it twice over. Finding 4 has been through three values:

| version | the efficiency curve was said to be worth | what was wrong |
|---|---|---|
| first | +30.3 % | the convex loss relaxation was degenerate during negative prices, where overstating charging loss lets the battery keep buying while capped |
| after the suite caught that | +13.3 % | the converter's no-load loss was charged around the clock instead of only while running, and the conventional arm was charged for auxiliaries the convention it represents does not include |
| after both were fixed | +3.6–4.0 % | the degradation anchor assumed a cycling rate rather than taking one from a field case, and the horizon was a pinned 24 hours rather than an overlapping one, so "rolling horizon" was not what was being run |
| current | +2.8–3.2 % | — |

Along the way the claim attached to this finding was withdrawn twice. It began as "the
efficiency curve is worth 30 % and moves the battery to half load", and ends as "the
curve is worth under 3 % and does not move dispatch; the money is in the auxiliary load".

None of those intermediate versions failed to solve, and none produced an implausible
schedule. Each was found by asking whether a quantity was the right *size*: an
auxiliary consumption of a quarter of throughput against a field range of 1–3 % is
what exposed the second error, not reading the code. Internal consistency is not
evidence of physical correctness, and the direction of the finding changed once the
sizes were right.

## Reproducing

```bash
pip install -r requirements.txt
PYTHONPATH=src python3 scripts/v0_arbitrage.py        2025-01-01 2025-03-31
PYTHONPATH=src python3 scripts/v1_reserve_headroom.py 2025-01-01 2025-03-31
PYTHONPATH=src python3 scripts/v2_capture_rate.py     2024-01-01 2025-12-31
PYTHONPATH=src python3 scripts/v3_converter_efficiency.py       2025-01-01 2025-06-30
PYTHONPATH=src python3 scripts/v4_service_differentiated_cdeg.py 2025-01-01 2025-06-30
PYTHONPATH=src python3 scripts/verify.py
PYTHONPATH=src python3 scripts/make_figures.py
```

Results are written to `results/` as CSV and JSON. First run downloads and caches
the market data; subsequent runs are offline.

## Status and what is not claimed

Work in progress. Rolling-horizon execution against an out-of-sample forecast is in
place, so the headline numbers are foresight-adjusted rather than theoretical, and a
load-dependent converter model is inside the optimiser. Next: combining the
efficiency curve with the reserve market so that the two effects interact, and
benchmarking against published GB revenue indices with the difference attributed
layer by layer rather than asserted to match.

One decomposition assumption is worth stating plainly: the field figures used to
calibrate the converter are *system* round-trip efficiencies, and splitting them into
a no-load term and a load-dependent term is a modelling choice, not a measurement.
The split is what makes the loss enter a linear program exactly; a different split
would move revenue between the standing-draw and the load-dependent channels without
changing their sum.

Leakage discipline is structural, not by care: every forecast feature is a lag, the
model is refit only on data strictly before each forecast origin, and realised prices
enter settlement but never the optimiser.

Not claimed: absolute revenue prediction for any real asset; prediction of any
specific battery's capacity in year 10 (system-level degradation ground truth does
not exist publicly); optimal price forecasting accuracy.

## Sources

Degradation parameters: NREL BLAST-Lite (BSD-3), fitted to Naumann et al.
(doi:10.1016/j.est.2018.01.019, doi:10.1016/j.jpowsour.2019.227666) and Gasper et
al. (doi:10.1016/j.est.2023.109042). Service ageing ratio: Frontiers in Energy
Research 13 (2025), doi:10.3389/fenrg.2025.1528691. Field degradation:
doi:10.1016/j.est.2023.107232, doi:10.5281/zenodo.12091223, EPRI Journal. Market
data: Elexon Insights.
