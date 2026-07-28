# BESS revenue stack — what published battery revenue models get wrong, quantified

Grid-scale battery revenue models are easy to write and easy to get wrong in ways
that do not announce themselves. The model still solves. The dispatch schedule
still looks reasonable. The revenue number is simply too high, and nothing in the
output says so.

This project measures how much too high, one modelling shortcut at a time, on real
GB market data with a battery degradation cost anchored to observed field data.
The backtester exists to produce those numbers; the numbers are the point.

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
```

Results are written to `results/` as CSV and JSON. First run downloads and caches
the market data; subsequent runs are offline.

## Status and what is not claimed

Work in progress. Currently at perfect foresight, which is an upper bound, not a
revenue forecast. Next: a price forecaster and rolling-horizon execution, which is
where the honest number comes from — the gap between the two is the quantity that
distinguishes a serious model from a marketing one.

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
