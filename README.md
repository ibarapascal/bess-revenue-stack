# BESS revenue stack — what four common modelling shortcuts cost, measured on GB market data

Grid-scale battery revenue models are easy to write and easy to get wrong in ways
that do not announce themselves. The model still solves. The dispatch schedule
still looks reasonable. The revenue number is simply too high, and nothing in the
output says so.

This project measures how much too high, one modelling shortcut at a time, on real
GB market data with a battery degradation cost anchored to observed field data.
The backtester exists to produce those numbers; the numbers are the point.

It is a controlled experiment on one asset in one market, not a survey of the
literature: the shortcuts are shown to be *costly* here, and shown to be *common* by
citation (see How this relates to published work, which also names the published paper
that makes the same overall argument).

![waterfall](figures/waterfall.png)

Of £3.15m of perfect-foresight gross margin over 2024–2025 for a 50 MW / 100 MWh
battery, forecast error removes £1.49m and degradation cost removes a further
£1.28m. What is left, £0.38m, is what the asset could actually have earned. A model
that reports the first number and calls it revenue is wrong by a factor of eight.

## Findings so far

All figures below: 50 MW / 100 MWh battery, GB wholesale (Elexon MID/APXMIDP). Findings
1 and 2 use Q1 2025, findings 4 and 5 use H1 2025, and finding 3 uses March 2024 to
January 2026. Every finding except 3 runs on perfect foresight, which is a theoretical
upper bound and never achievable — it is used because these are *relative* comparisons
where both arms share the same advantage. Finding 3 is the one that measures what
dropping that advantage costs.

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

![degradation](figures/degradation.png)

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

**4. The two errors hiding inside a flat efficiency assumption have opposite signs. For
a 2-hour battery they very nearly cancel, and everything that survives is the auxiliary
load.**

Loss has a load-independent part and a part growing with the square of current.
Calibrated to the *AC round-trip* efficiency of a utility-scale plant — measured AC
terminal to AC terminal at eleven power setpoints, so it excludes auxiliaries but
contains both power-electronic and cell losses:

| load | 5 % | 10 % | 25 % | 50 % | 75 % | 100 % |
|---|---|---|---|---|---|---|
| round-trip efficiency | 0.62 | 0.77 | 0.89 | 0.93 | 0.94 | 0.94 |

The important feature is that this curve **beats a flat 0.9 everywhere above about a
quarter load** — and a 2-hour battery discharges at 86 % of rated on average. Four arms,
each isolating one omission (H1 2025, thermal load 0 to 0.2 MW):

| arm | net revenue (£) | |
|---|---|---|
| conventional: flat 0.9, no auxiliary draw | 624,632 | what a typical model prints |
| the same schedule, paying auxiliaries | 511,388–586,556 | costs £38k–£113k |
| the same schedule, also settled on the real curve | 554,542–629,710 | *gains* £43k back |
| optimised with the curve inside the program | 578,745–653,914 | a further 3.8–4.4 % |

| thermal load | 0 MW | 0.05 MW | 0.10 MW | 0.20 MW |
|---|---|---|---|---|
| conventional model overstated by | **−0.8 %** | 2.2 % | 5.5 % | 12.6 % |
| of which: auxiliary consumption | +£38,076 | +£56,868 | +£75,660 | +£113,244 |
| of which: efficiency curve shape | −£43,154 | −£43,154 | −£43,154 | −£43,154 |

![efficiency error](figures/efficiency_error.png)

With no standing thermal load the conventional model is 0.8 % *low*, not high: the
efficiency it gets wrong is wrong in the generous direction, and that gain slightly
exceeds the no-load draw it ignores. Every pound of net overstatement therefore traces
to the standing auxiliary load, and grows roughly linearly with it. Putting the curve
inside the optimiser is worth 3.8–4.4 % and does shift dispatch, from 86.3 % to 90.4 %
of rated discharge load, because an auxiliary-excluded curve rises monotonically toward
rated power rather than peaking mid-load.

Two things make this the finding the project has got wrong most often. The efficiency
figure that is easiest to find for this plant — 85 % at full power falling to 65 % at low
power — is its *global* efficiency, whose denominator includes auxiliary energy; using it
here while separately charging thermal load and no-load loss counted auxiliaries twice.
And most of that 85→65 droop is not part-load electronics at all: on that plant a full
cycle takes 26.4 hours at 0.1 p.u. against 2.6 hours at rated, so a near-constant
auxiliary draw is being integrated over ten times the exposure. A time integral had been
folded into a power-indexed efficiency curve. See Verification below for the full history.

**5. Pricing wear by service decides whether the battery enters the reserve market at
all — not just what it books.**

Module tests under real grid duty profiles put peak-shifting ageing at 1.81–1.92×
frequency regulation at comparable throughput (Xu et al. 2025, 220 Ah LFP). The sign is
corroborated on a different chemistry and by a different measurement convention:
Ohrelius et al. cycled NMC532/graphite cells under five grid duty profiles and report "a
slower trend for FR and a faster rate for PS", attributing it to state-of-charge swing
amplitude rather than C-rate (2024), and the same group's lifetime study puts frequency
regulation at 12 years against 8 for peak shifting, a ratio near 1.5 (2023). No study
found during the literature check reports the opposite direction. Carrying that
distinction, rather than one degradation cost for all energy:

| reserve price (£/MW/h) | mean reserve held, one cost | with 1.85× ratio | cycling | net |
|---|---|---|---|---|
| 2 | 0.00 MW | 22.13 MW | −4.5 % | +4.3 % |
| 5 | 37.95 MW | 41.89 MW | −18.1 % | +28.0 % |
| 10 | 46.25 MW | 46.74 MW | −8.3 % | +15.6 % |

![service-differentiated wear](figures/service_cdeg.png)

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
known to violate. Two provenance caveats point the same way — the 220 Ah modules are
second-life cells, and all authors of that study are at one instrument manufacturer. The
ratio is therefore swept from 1.0 to 2.5 rather than asserted, and the corroborating
studies bracket rather than confirm 1.85.

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

**Auxiliary consumption is separated by where it actually arises, and kept out of the
efficiency curve.** The load-independent loss inside the AC round-trip curve (0.69 MW,
1.4 % of rated) is charged only in periods when the converter runs, gated by one binary
per period. Thermal management is the genuinely round-the-clock part, is modelled as
power times time rather than as an efficiency penalty, and is swept over 0–0.2 MW. That
range is an order of magnitude reasoned from the 1–3 % of throughput field data supports,
not a field anchor: the source plant never discloses its auxiliaries' nominal rating, so
an absolute standing draw cannot be taken from it. Keeping auxiliaries out of the
efficiency metric is what stops the same energy being charged twice.

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

## How this relates to published work

This project is **not** the first to argue that modelling shortcuts inflate battery
revenue. That argument is published, and the closest paper states the thesis of this
repository almost exactly.

**Mohamed, Rigo-Mariani & Debusschere (2025)**, *Impact of modeling assumptions on the
economic performance assessment of a storage participating in energy and reserve
markets*, Journal of Energy Storage 133, 117998, doi:10.1016/j.est.2025.117998. Isolates
three simplifications — constant operating efficiency, neglected profit loss from
uncertainty, degradation computed after the fact — and reports up to 30 % overestimation
of lifetime profit, more than 60 % in the worst cases, on continental day-ahead plus FCR.
Three things differ here rather than one: results are decomposed *per assumption* instead
of by asset size, the data are GB Elexon half-hourly for 2024–2025, and two further
dimensions enter that paper does not cover — auxiliary consumption and forecast skill.
Anyone reading this repo as novel should read that paper first.

On the individual layers:

| published work | what it establishes | how this differs |
|---|---|---|
| Kumtepeli et al. (2024), ACC, doi:10.23919/ACC60939.2024.10644173 | depreciation cost is a poor proxy for revenue lost to ageing; profit 30–50 % below the best-parameterised case | measures the error in *reported revenue*, not the loss from a suboptimal dispatch rule |
| Jafari, Botterud & Sakti (2020), Applied Energy 276, 115417 | simplified battery representations overstate offshore wind-storage revenue by ~35 % | GB standalone asset on 2024–2025 data; overstatement split into attributable layers rather than one total |
| Falezza (2026), arXiv:2604.12082 | forecast skill maps non-linearly to revenue; Kendall τ, not MAE, is the decision-relevant axis; persistence captures 32.8 % of oracle | see the reconciliation below |
| Humiston, Cetin & de Queiroz (2026), Energies 19(4) 1056 | linear-calendar and energy-throughput ageing give ≈2 %/yr and modest economic impact; rainflow gives much higher loss, large negative valuation, and is highly sensitive to calibration | that calibration sensitivity is the failure mode field anchoring here is built to avoid; their design deliberately holds dispatch fixed, whereas dispatch response is the object of study here |
| Cornejo et al. (2025), ISGT Europe, doi:10.1109/ISGTEurope64741.2025.11305340 | putting a non-linear equivalent-circuit loss model inside an MPC is worth 0.4 / 1.9 / 3.8 % at internal-resistance multipliers of 1 / 2 / 3 | the comparable fresh-asset figure there is 0.4 %, against 3.8–4.4 % here; the gap is the calibration basis, not the mechanism (see Status) |
| Gatta et al. (2015), IEEE PowerTech, doi:10.1109/PTC.2015.7232464 | auxiliary loads are "usually disregarded in studies concerning BESS integration" | supplies the prevalence evidence for finding 4 rather than asserting it |
| Schimpe et al. (2018), Applied Energy 210, 211–229 | 18 loss mechanisms in a container system; power-electronic losses exceed cell losses at low operating power | the mechanism behind the curve shape used here |
| Gale et al. (2026), J. Energy Storage 166, 122328 | GB balancing-market access is worth £166,123/MW/yr against £47,234/MW/yr for wholesale alone — but the first figure assumes unconstrained BM access, and the paper notes real batteries skip over 90 % of instructions and that a commercial GB battery earned £101k/MW/yr from all sources in 2023; revenue falls about £12,000/MW/yr per 10 points of skip rate | orthogonal: that paper adds markets to the stack, this one audits assumptions *within* one market. Its wholesale-only figure is the closest published like-for-like comparison and is used as such below |
| Vykhodtsev et al. (2022), Renewable and Sustainable Energy Reviews 166, 112584 | taxonomy of battery models used in techno-economic analysis | classifies the modelling choices without quantifying what they cost, which is the gap addressed here |

**Reconciling finding 3 with Falezza (2026).** That paper reports near-complete capture
at high forecast skill; the LightGBM arm here captures 21 % of net revenue. The numbers
are not in conflict because they measure different assets in different markets: a
10 MW / 10 MWh unit across FCR, aFRR, day-ahead and intraday in DE/CH, where the reserve
capacity payments do not depend on a price forecast at all, against a 50 MW / 100 MWh
unit on GB wholesale alone, where every pound is forecast-dependent by construction. The
methodological point stands on its own merits, and this repo partly concedes it: `v2`
reports within-day rank correlation (0.58 persistence, 0.65 LightGBM) and direction
accuracy alongside MAE, precisely because MAE is a weak proxy for dispatch quality. The
skill axis in the transmission figure is still MAE, which is the honest limitation — a
τ-indexed sweep would be the better experiment and has not been run.

**On prevalence.** The claim that these shortcuts are common is cited, not asserted:
Mohamed et al. open on "most studies assume oversimplifications", Gatta et al. record
that auxiliary loads are usually disregarded, and Vykhodtsev et al. document the
modelling conventions in use. What this repo does not have is a survey counting how many
published models take each shortcut, so "common" rests on those three sources rather than
on a census.

**What the literature check did not settle.** Body text could not be reached for Gatta
et al. (2015) or for the published Jafari et al. (2020) — the 35 % figure comes from the
publisher abstract, and the widely-cited 155 % in the preprint version compares gross
revenue under one model against net revenue under another, a base mismatch the paper
itself concedes reduces to 29 % when made consistent. That is the same error this project
made in an early version of `v0`, which is why it is spelled out rather than cited
silently.

## Does any of this land near the real market?

A model that says a GB battery earns £4k/MW/yr when published indices say £73k is either
measuring something narrower or is wrong, and the difference has to be accounted for
rather than asserted. Every figure here is normalised to £/MW/yr for the same
50 MW / 100 MWh asset.

| | £/MW/yr | scope |
|---|---|---|
| this project, degradation ignored, perfect foresight (Q1 2025) | 53,026 | wholesale arbitrage only |
| **Gale et al. (2026), modelled, wholesale only, 100 MW / 1 h, June 2020 – June 2023** | **47,234** | wholesale arbitrage only, marginal cost £0.5/MWh |
| this project, field-anchored degradation, perfect foresight (Q1 2025) | 26,282 | wholesale arbitrage only |
| this project, same but over Mar 2024 – Jan 2026 | 19,376 | wholesale arbitrage only |
| this project, degradation + out-of-sample forecast | 4,142 | wholesale arbitrage only |
| Modo Energy, realised, typical 2 h GB BESS, 12 months to Apr 2026 — wholesale + balancing only | 43,829 | 60 % of that fleet's stack |
| Modo Energy, same asset and period, **full stack** | 73,145 | + Capacity Market (7,454) + ancillary (33 % gross) |
| Gale et al. citing Modo: a real commercial GB battery, all sources, Jan–Aug 2023 | ~101,000 | full stack |

The top line is the comparison that matters, because it is the only like-for-like one:
wholesale arbitrage, before degradation is priced, on a perfect-foresight schedule. At
£53.0k against £47.2k the two agree within 12 % despite different years, durations and
optimisers. **The apparent order-of-magnitude discrepancy is therefore not a modelling
error — it is the deductions this project exists to measure, plus the markets it
deliberately excludes.** Reading down the table: pricing wear at the field-anchored
£30.56/MWh halves the figure, extending the window past the high-spread months halves it
again, and replacing foresight with a real forecast removes three quarters of what is
left. None of those three steps is present in any published index.

What is excluded is as important. This asset trades one price series. It does not touch
the Balancing Mechanism, holds no ancillary contracts, and earns no Capacity Market
derating payment — the last of which alone is £7,454/MW/yr in the Modo breakdown.
Consistent with that, `v1` shows a single reserve stream at £5–10/MW/h lifting net revenue
to £47k–£87k/MW/yr, which brackets the £73k full-stack benchmark.

Two limits on how far this can be pushed. Modo's index methodology sits behind a login,
so whether it is gross or net of degradation cannot be established — it therefore cannot
validate the degradation layer specifically, only the gross arbitrage layer. And no
published GB *capture rate* exists to compare against: Modo publishes the definition
(revenue divided by a theoretical maximum from real-time top-bottom spreads) and ERCOT
values ranging 38 % in January 2025 to 85 % in May, but no GB series. Modo's own GB
forecast note concedes that "the reality is quite different to a 24-hour perfect foresight
model" without quantifying the gap, which is the gap `v2` measures.

Two widely-repeated figures were checked and are **not** used here, because tracing them
found no source. A claim that GB batteries captured "44 % of available EET, up from 36 %"
resolves, on Modo's actual page, to 49 % (and 70 % versus 32 % by duration) — and refers
to the Embedded Export Tariff across three Triad half-hours, far too narrow to represent
annual capture. A claim that perfect foresight overstates arbitrage revenue by only
10–15 % appears in search-engine summaries attributed to two papers, neither of which
contains the number or concerns GB. Both appear to be artefacts of AI-generated search
summaries.

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

The suite earned its place immediately, then a full review of the repository earned it
twice over, and a check of every citation against its source earned it a third time.
Finding 4 has been through five values:

| version | the efficiency curve was said to be worth | what was wrong |
|---|---|---|
| first | +30.3 % | the convex loss relaxation was degenerate during negative prices, where overstating charging loss lets the battery keep buying while capped |
| after the suite caught that | +13.3 % | the converter's no-load loss was charged around the clock instead of only while running, and the conventional arm was charged for auxiliaries the convention it represents does not include |
| after both were fixed | +3.6–4.0 % | the degradation anchor assumed a cycling rate rather than taking one from a field case, and the horizon was a pinned 24 hours rather than an overlapping one, so "rolling horizon" was not what was being run |
| after re-anchoring both | +2.8–3.2 % | the efficiency curve was calibrated to the field plant's *global* efficiency, which includes auxiliary energy, while auxiliaries were also charged separately — so they were counted twice; and the low-load droop in that metric is mostly the ten-fold longer cycle duration at low power, not part-load electronics |
| current | +3.8–4.4 % | — |

The claim attached to this finding has now been withdrawn three times, and its *sign*
once. It began as "the efficiency curve is worth 30 % and moves the battery to half
load". It became "the curve is worth under 3 % and does not move dispatch". It now reads
"the flat 0.9 assumption is slightly conservative for this asset, all of the
overstatement is the auxiliary load, and modelling the curve is worth about 4 % and does
move dispatch — upward in load, not toward mid-load."

None of those intermediate versions failed to solve, and none produced an implausible
schedule. Each was found by asking whether a quantity was the right *size*, or whether a
cited number meant what the citation implied. An auxiliary consumption of a quarter of
throughput against a field range of 1–3 % exposed the second error. Reading the source
paper's own equations, rather than its abstract, exposed the fourth: two efficiency
metrics differing only by auxiliary energy, and the wrong one had been used. Neither was
found by reading our code, which was internally consistent throughout.

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
load-dependent loss model is inside the optimiser. Benchmarking against published GB
figures is done, with the difference attributed layer by layer rather than asserted to
match. Next: combining the efficiency curve with the reserve market so that the two
effects interact, and indexing the forecast-skill sweep by rank correlation rather than
by MAE.

Three decomposition assumptions are worth stating plainly.

The efficiency curve is calibrated to an AC-terminal round trip, which contains both
power-electronic and electrochemical losses and does not separate them; the source
paper says only that conversion losses dominate below 0.3 p.u. and cell phenomena
above 0.5 p.u. So `ConverterModel` is not a converter in the component sense — it is the
whole AC-to-AC path, which is why the battery's own flat efficiency is bypassed whenever
one is supplied. Splitting that curve into a no-load term and a quadratic term is a
modelling choice, not a measurement; it is what lets the loss enter a linear program
exactly, and a different split would move revenue between the standing-draw and
load-dependent channels without changing their sum.

The standing thermal draw has no absolute field anchor here, only an order of magnitude,
because the source plant never publishes its auxiliaries' nominal rating. It is swept.

The comparison to Cornejo et al. (2025) is not like-for-like. Their fresh-asset figure
for putting a non-linear loss model inside the optimiser is 0.4 %, against 3.8–4.4 %
here. The mechanism is the same but the baselines differ: their reference is an already
load-dependent linear model on a 180 kW asset in the German intraday market, whereas the
reference here is a flat 0.9 that misprices the high-load band a 2-hour GB asset actually
uses. The gap is the calibration basis, and it has not been reconciled experimentally.

Leakage discipline is structural, not by care: every forecast feature is a lag, the
model is refit only on data strictly before each forecast origin, and realised prices
enter settlement but never the optimiser.

Not claimed: absolute revenue prediction for any real asset; prediction of any
specific battery's capacity in year 10 (system-level degradation ground truth does
not exist publicly); optimal price forecasting accuracy.

## Sources

**Degradation model.** NREL BLAST-Lite (BSD-3), fitted to Naumann et al.
(doi:10.1016/j.est.2018.01.019, doi:10.1016/j.jpowsour.2019.227666) and Gasper et al.
(doi:10.1016/j.est.2023.109042).

**Service ageing ratio.** Xu, Li, Hua & Wang (2025), *Experimental investigation of grid
storage modes effect on aging of LiFePO4 battery modules*, Frontiers in Energy Research
13, 1528691, doi:10.3389/fenrg.2025.1528691. Corroborated by Ohrelius, Wreland Lindström
& Lindbergh (2024), *Lithium-Ion Battery Degradation in Grid Applications*, J.
Electrochem. Soc. 171(12) 120501, doi:10.1149/1945-7111/ad92db, and Ohrelius, Berg,
Wreland Lindström & Lindbergh (2023), *Lifetime Limitations in Multi-Service Battery
Energy Storage Systems*, Energies 16(7) 3003, doi:10.3390/en16073003.

**Field degradation and efficiency.** Grimaldi, Minuto, Perol, Casagrande & Lanzini
(2023), *Ageing and energy performance analysis of a utility-scale lithium-ion battery
for power grid applications through a data-driven empirical modelling approach*, J.
Energy Storage 65, 107232, doi:10.1016/j.est.2023.107232 — the Italian field pair and the
efficiency calibration. Additional degradation rates: doi:10.5281/zenodo.12091223, EPRI
Journal.

**Comparison to published modelling-assumption studies.** See How this relates to
published work for the full list, headed by Mohamed, Rigo-Mariani & Debusschere (2025),
doi:10.1016/j.est.2025.117998.

**Market data.** Elexon Insights (open, no API key).

Every reference above was checked against Crossref or publisher metadata rather than
carried over from memory; where only an abstract could be read, the section that cites it
says so.
