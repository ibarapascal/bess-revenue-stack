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

## Reproducing

```bash
pip install -r requirements.txt
PYTHONPATH=src python3 scripts/v0_arbitrage.py        2025-01-01 2025-03-31
PYTHONPATH=src python3 scripts/v1_reserve_headroom.py 2025-01-01 2025-03-31
PYTHONPATH=src python3 scripts/v2_capture_rate.py     2024-01-01 2025-12-31
PYTHONPATH=src python3 scripts/make_figures.py
```

Results are written to `results/` as CSV and JSON. First run downloads and caches
the market data; subsequent runs are offline.

## Status and what is not claimed

Work in progress. Rolling-horizon execution against an out-of-sample forecast is in
place, so the headline numbers are foresight-adjusted rather than theoretical. Next:
a converter efficiency curve and thermal parasitic load, where field measurement of a
utility-scale plant puts round-trip efficiency at 85 % near rated power but 65 % at
low load — against the constant 0.9 that most public models assume.

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
