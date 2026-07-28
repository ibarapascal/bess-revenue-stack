# BESS revenue stack — what published battery revenue models get wrong, quantified

Grid-scale battery revenue models are easy to write and easy to get wrong in ways
that do not announce themselves. The model still solves. The dispatch schedule
still looks reasonable. The revenue number is simply too high, and nothing in the
output says so.

This project measures how much too high, one modelling shortcut at a time, on real
GB market data with a battery degradation cost anchored to observed field data.
The backtester exists to produce those numbers; the numbers are the point.

![waterfall](figures/waterfall.png)

Of £3.56m of perfect-foresight gross margin over 2024–2025 for a 50 MW / 100 MWh
battery, forecast error removes £1.61m and degradation cost removes a further
£1.17m. What is left, £0.77m, is what the asset could actually have earned. A model
that reports the first number and calls it revenue is wrong by a factor of 4.6.

## Findings so far

All figures below: 50 MW / 100 MWh battery, GB wholesale (Elexon MID/APXMIDP),
Q1 2025, perfect foresight. Perfect foresight is a theoretical upper bound and is
never achievable — it is used here because these are *relative* comparisons where
both arms share the same advantage.

**1. Ignoring degradation cost overstates arbitrage revenue by 38–99% and implies
uneconomic cycling.**

| degradation assumption | c_deg (£/MWh) | net revenue (£) | £/MW/yr | implied cycles/yr |
|---|---|---|---|---|
| ignored, as in many public models | 0 | 629,023 | 51,009 | 683 |
| field-anchored, 1.4 %/yr loss | 12.4 | 455,006 | 36,897 | 490 |
| field-anchored, 2.0 %/yr loss | 17.7 | 396,264 | 32,134 | 416 |
| field-anchored, 3.0 %/yr loss | 26.5 | 316,854 | 25,694 | 323 |

683 equivalent full cycles per year is close to two full cycles per day. No owner
operates that way, because the battery is a consumable. Pricing that consumption
changes both the revenue and the behaviour: cycling falls by 28–53 % and the
revenue that survives is 38–99 % lower.

**2. Omitting the state-of-charge headroom constraint overstates net revenue by
2–11%, by selling reserve the battery could not have delivered.**

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
| 2 | 444,043 | 487,391 | 9.8 % | 27.7 → 40.7 |
| 5 | 680,139 | 756,179 | 11.2 % | 41.3 → 42.2 |
| 10 | 1,154,515 | 1,225,276 | 6.1 % | 46.0 → 44.7 |
| 20 | 2,181,101 | 2,225,094 | 2.0 % | 48.4 → 47.5 |

The revenue error is worst when reserve is cheap enough that the battery must
genuinely choose between markets — which is most of the time. At £2/MW/h the model
without the constraint commits 47 % more reserve than it can back with energy.

**3. A day-ahead forecast captures 55% of perfect-foresight gross margin but only
34% of net revenue — degradation cost amplifies forecast error rather than scaling
with it.**

| arm | forecast MAE (£/MWh) | gross margin | net revenue | net capture |
|---|---|---|---|---|
| perfect foresight | 0 | 3,556,000 | 2,280,472 | 100 % |
| LightGBM day-ahead | 20.1 | 1,941,444 (55 %) | 771,441 | 33.8 % |
| naive (yesterday, same period) | 21.2 | 1,859,624 (52 %) | 585,443 | 25.7 % |

The gap between the gross and net columns is the finding. A battery pays for its own
wear on every cycle whether or not the trade was profitable, so an imperfect forecast
loses margin twice: once in the trade, and again in the degradation spent chasing it.
Models that ignore degradation never see this, and models that report gross margin
hide it.

![transmission](figures/transmission.png)

The transmission from forecast skill to revenue is strongly non-linear. Cutting MAE
by a quarter, from £20.1 to £15.1/MWh, doubles net capture from 34 % to 69 %; the
remaining three quarters of the improvement buy only the last 31 points. For an
operator this reverses the usual intuition about where to spend effort.

*Scope*: this applies to a strategy priced off the half-hourly reference price, which
is not known in advance. It does not apply to day-ahead auction arbitrage, where the
clearing price is known at gate closure and perfect foresight is close to achievable
for that leg. The forecast-dependent part of a real revenue stack is within-day and
balancing.

**4. A flat round-trip efficiency does not just overstate revenue — it makes the
battery operate at the wrong power level.**

Converter loss has a load-independent part and a part that grows with the square of
current, so efficiency peaks near half load and falls at both ends. Calibrated to
field measurement of a utility-scale plant (85 % round trip at rated, 65 % at 10 %
load), the curve is:

| load | 5 % | 10 % | 25 % | 50 % | 75 % | 100 % |
|---|---|---|---|---|---|---|
| round-trip efficiency | 0.46 | 0.65 | 0.81 | 0.86 | 0.86 | 0.85 |

| arm | net revenue (H1 2025) | vs truth |
|---|---|---|
| flat efficiency, as the model reports it | 329,209 | overstated by 8.5 % |
| the same schedule, settled under the real curve | 303,488 | — |
| optimised with the curve inside the program | 343,974 | +13.3 % |

The first gap is the accounting error. The second is the operating error, and it is
the larger of the two: knowing the curve moves mean discharge from 87 % to 50 % of rated power,
toward the efficiency peak, rather than pushing for maximum power whenever the
spread looks good. A model carrying a constant 0.9 cannot see that trade-off exists.

Auxiliary draw is treated separately because it is not part of round-trip efficiency
at all: it runs whether or not the battery cycles. The converter's no-load loss
(1.17 MW, 2.3 % of rated) is applied as a standing draw in every arm, and thermal
management is swept on top rather than asserted, because published BESS auxiliary
figures vary too widely to pick one. At 0.5 MW of thermal load the accounting error
grows from 8.5 % to 22.3 %.

**5. Pricing wear by service rather than by the megawatt-hour changes what the
battery does, not just what it reports.**

Module tests under real grid duty profiles put peak-shifting ageing at 1.81–1.92×
frequency regulation at comparable throughput. Carrying that distinction into the
optimiser, rather than one degradation cost for all energy:

| reserve price (£/MW/h) | mean reserve held, one cost | with 1.85× ratio | cycling change | net change |
|---|---|---|---|---|
| 2 | 17.9 MW | 27.4 MW (+53 %) | −13 % | +10.2 % |
| 5 | 38.3 MW | 40.3 MW (+5 %) | −10 % | +11.6 % |
| 10 | 45.2 MW | 45.6 MW (+1 %) | −8 % | +7.6 % |

The effect is largest where the choice is genuinely open: at a low reserve price the
single-cost model keeps the battery in the wholesale market, while the differentiated
model recognises that reserve duty is gentler on the cells and moves half again as
much capacity into it. At high reserve prices both models go to reserve anyway and
the distinction only affects the books.

This one rests on the shakiest assumption in the project, and it is stated in the
code: mapping a capacity-loss ratio onto a marginal-cost ratio presumes damage
accumulates linearly with throughput, which is the approximation degradation physics
is known to violate. The ratio is therefore swept from 1.0 to 2.5 rather than
asserted.

## What is different here

**Degradation level comes from the field, shape comes from the cell.** Public
cell-level ageing models (NREL BLAST-Lite, parameterised on Naumann et al. and on
NREL's own large-format prismatic tests) predict 5–7 %/yr capacity loss at 300
equivalent full cycles. Measured whole-system loss is 1.4–3 %/yr: 1.37 %/yr at an
Italian utility-scale plant, ~2.3 %/yr in independent EPRI measurement of a system
whose vendor self-reported 0.5 %/yr, and 2–3 %/yr across 21 German systems tracked
for 8 years. Running the cell models unscaled would price degradation above
realistic spreads and silently shut off all trading. Here the cell model supplies
the *response* to depth, rate and temperature; the field range supplies the
*level*; and the 1.4–3 %/yr spread is carried through as a band rather than
collapsed to one number, because no public dataset of container-scale degradation
exists to narrow it.

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

The suite earned its place immediately: it found that the convex loss relaxation was
degenerate during negative prices, where the program could profit from overstating
charging loss. Before the fix, finding 4 read "+30.3 %"; after it, "+13.3 %". A
headline number was inflated by a factor of 2.3 by a bug that produced entirely
plausible schedules and revenues.

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
