# BESS revenue stack — what four common modelling shortcuts cost, measured on GB market data

Grid-scale battery revenue models are easy to write and easy to get wrong in ways that do
not announce themselves: the model still solves, the schedule still looks reasonable, and
the revenue number is simply too high. This measures how much too high, one shortcut at a
time, on real GB market data — a 50 MW / 100 MWh battery on Elexon half-hourly prices,
March 2024 to January 2026, every finding on the same asset and the same window.

## The five results

| # | shortcut | what it costs | the catch |
|---|---|---|---|
| 1 | pricing wear at zero | overstates net revenue **79–134 %**, and implies 729 full cycles a year against 243 | the wear price itself is a four-input calculation, only one of which is measured |
| 2 | no state-of-charge headroom for reserve | overstates **2–13 %** — at £2/MW/h it commits 44.3 MW of reserve against 25.0 MW it could deliver | reserve prices here are a synthetic sweep, not market data |
| 3 | assuming you can forecast | a real forecast captures **53 % of gross margin but only 21 % of net** | wear is charged on every cycle, right or wrong, so it amplifies forecast error instead of scaling with it |
| 4 | one flat round-trip efficiency | **the two errors inside it have opposite signs** — with no thermal load the flat assumption is 0.4 % *low*, and all the overstatement (to 15.5 %) is the auxiliary load nobody models | holds for a 2-hour asset discharging at 86 % of rated; a longer-duration asset may well flip it |
| 5 | one wear price for every service | decides **whether the battery enters the reserve market at all** — 0.00 MW under one price, 25.0 MW when reserve duty is priced at its measured 1.85× lower ageing | the flip sits between ageing ratios of 1.5 and 1.85, and the supporting studies straddle that |

Findings 1, 2, 4 and 5 compare two arms under perfect foresight, which is an unreachable
upper bound used because both arms share it. Finding 3 is the one that measures what
losing it costs.

![waterfall](figures/waterfall.png)

Stacked together on the forecast-driven case: of £3.15m of perfect-foresight gross margin,
forecast error removes £1.49m and degradation cost removes a further £1.28m, leaving
£0.38m.

Two qualifications belong next to that number rather than deeper in the page. It describes
a **wholesale-only strategy indexed to the half-hourly reference price** — a real GB
battery also trades the day-ahead auction, where the clearing price is known at gate
closure and forecast error costs far less, so £0.38m is the achievable revenue of the
forecast-dependent leg, not of the asset. And the size of the gap is set by how wear is
priced: **8.3× at £30.6/MWh, 4.1× at the £20.3/MWh implied by the EPRI field loss rate**.
A factor of four to eight, with the degradation price as the dominant input, is the honest
headline. The top bar is itself the gross margin of a schedule that already prices
degradation; a model ignoring wear entirely would cycle 729 times a year and print £4.17m.

This is a controlled experiment on one asset in one market, not a survey. The shortcuts
are shown to be *costly* here and shown to be *common* by citation — see How this relates
to published work, which also names the published paper that makes the same overall
argument and reaches the opposite conclusion on finding 4.

## The five results in detail

Running every finding on one window is deliberate: shorter windows in this dataset have
wider spreads, so choosing a quarter per finding would let each effect be reported at its
most flattering. Doing the opposite turned out to strengthen the results rather than
soften them.

**1. Ignoring degradation cost overstates arbitrage revenue by 79–134 % and implies
cycling no owner would accept.**

A degradation cost cannot be set from an annual loss rate alone: the same 2 %/yr means
a very different cost per MWh depending on how hard the asset was cycled to get there.
Only one public field case reports both — an Italian utility-scale plant, 356
equivalent full cycles over three years to 95.9 % state of health, so 119 EFC/yr at
1.37 %/yr. The other field cases give a rate without a cycle count and enter as
sensitivity under an assumed 300 EFC/yr, labelled as such rather than as calibration.

**What "field-anchored" does and does not mean.** At the reference operating point the
cost reduces to a closed form in four inputs — replacement cost, discount factor, the
field loss-per-cycle pair, and usable depth — of which only the pair is a measurement.
The other three are conventions and the answer is sensitive to them: a discount rate
swept over 0–12 % moves c_deg from £76.9 to £19.8/MWh, replacement cost over
£80–160k/MWh from £20.4 to £40.7, assumed life over 8–15 years from £41.6 to £24.3. The
cell model supplies a response to depth, rate and temperature away from that reference
point, but every number published here is *at* the reference point, so none of them
exercises it. Anchoring pins the level to observed hardware; it does not turn c_deg into
a measured quantity.

It is also worth saying plainly that £30.6/MWh sits well above published practice —
industry convention is roughly £2–8/MWh and Gale et al. (2026) use £0.50/MWh for a GB
asset. The gap is not a modelling slip: those figures are marginal-cost proxies, whereas
this one is a replacement-cost amortisation over an observed field loss rate. But a
reader whose prior is £5/MWh should know the disagreement is two orders of magnitude and
that findings 2 to 5 all run at the £30.6 end.

| degradation assumption | c_deg (£/MWh) | net revenue (£) | £/MW/yr | cycles/yr |
|---|---|---|---|---|
| ignored, as in many public models | 0 | 4,169,625 | 45,295 | 729 |
| Italian field pair (1.37 %/yr at 119 EFC) | 30.6 | 1,783,084 | 19,370 | 243 |
| EPRI 2.3 %/yr, EFC assumed 300 | 20.3 | 2,333,982 | 25,354 | 344 |
| German upper 3 %/yr, EFC assumed 300 | 26.5 | 1,979,724 | 21,506 | 280 |

![degradation](figures/degradation.png)

729 equivalent full cycles per year is two a day, every day, for two years. Pricing the
wear cuts cycling by 53–67 % and removes 79–134 % of the revenue, and the only row
derived entirely from field observation is the most severe of the three.

**2. Omitting the state-of-charge headroom constraint overstates net revenue by
2–13 %, by selling reserve the battery could not have delivered.**

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
| 2 | 1,893,079 | 2,031,541 | 7.3 % | 25.0 → 44.3 |
| 5 | 3,719,870 | 4,207,347 | 13.1 % | 43.4 → 45.5 |
| 10 | 7,431,027 | 7,928,445 | 6.7 % | 47.5 → 46.7 |
| 20 | 15,234,360 | 15,565,013 | 2.2 % | 48.9 → 48.0 |

The clearest case is £2/MW/h, where the model without the constraint commits nearly twice
the reserve it can back with energy — 44.3 MW against a deliverable 25.0 MW. The revenue
error peaks at £5 rather than at £2 because at £2 the battery holds little reserve either
way, and at £10–20 availability pays so well that both arms saturate; the two rows where
adding the constraint slightly *raises* mean reserve are a rescheduling effect, not a
solver artefact — the constrained problem shifts when it charges in order to keep
headroom, and ends up holding reserve in more periods at a lower average depth.

Two disclosures. **The reserve price here is a synthetic flat constant, not market data**
— £2/5/10/20 per MW/h swept, with £20 well above 2024–25 GB clearing levels and included
as a stress point. Only the energy prices are real. And this experiment's baseline already
prices reserve wear below arbitrage wear at the 1.85 ratio of finding 5, which is why it
holds 25.0 MW at £2 while the single-cost model in finding 5 holds none at the same price.
The two tables are consistent; they are not the same baseline.

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

Cutting MAE by a quarter, from £20.1 to £15.1/MWh, triples net capture from 21 % to 61 %;
the remaining three quarters of the improvement buy the last 39 points. On an error axis
the transmission looks strongly non-linear — and that reading does not survive changing
the axis.

The sweep is generated by blending the model's forecast toward the realised price, which
lowers MAE and injects oracle *ordering* at the same time. A battery earns on the
ordering. Both axes are therefore reported:

| | capture 21 → 61 % | 61 → 84 % | 84 → 96 % | 96 → 100 % |
|---|---|---|---|---|
| slope per £1/MWh of MAE removed | 7.9 | 4.5 | 2.4 | 0.8 |
| slope per unit of rank correlation | 256 | 222 | 183 | 175 |

Across the whole sweep the slope varies about tenfold on the error axis and 1.5-fold on
the ordering axis. The £15.1 MAE point carries a within-day rank correlation of 0.81,
while both genuine forecasters sit at 0.58–0.65. **So the non-linearity is largely a
property of the axis, not of forecasting**, and the load-bearing result in this finding is
the gross-versus-net gap in the table above, which needs no skill axis at all. A sweep over
genuinely different forecasters would settle what real skill improvement buys; it has not
been run.

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
| conventional: flat 0.9, no auxiliary draw | 1,783,084 | what a typical model prints |
| the same schedule, paying auxiliaries | 1,428,406–1,675,113 | costs £108k–£355k |
| the same schedule, also settled on the real curve | 1,544,269–1,790,975 | *gains* £116k back |
| optimised with the curve inside the program | 1,619,074–1,865,781 | a further 4.2–4.8 % |

| thermal load | 0 MW | 0.05 MW | 0.10 MW | 0.20 MW |
|---|---|---|---|---|
| conventional model overstated by | **−0.4 %** | 3.1 % | 6.9 % | 15.5 % |
| of which: auxiliary consumption | +£107,972 | +£169,648 | +£231,325 | +£354,678 |
| of which: efficiency curve shape | −£115,863 | −£115,863 | −£115,863 | −£115,863 |

![efficiency error](figures/efficiency_error.png)

With no standing thermal load the conventional model is 0.4 % *low*, not high: the
efficiency it gets wrong is wrong in the generous direction, and that gain slightly
exceeds the no-load draw it ignores. Every pound of net overstatement therefore traces
to the standing auxiliary load, and grows roughly linearly with it. Putting the curve
inside the optimiser is worth 4.2–4.8 % and does shift dispatch, from 86.2 % to 90.2 %
of rated discharge load, because an auxiliary-excluded curve rises monotonically toward
rated power rather than peaking mid-load.

Which efficiency figure is used decides this finding, so it is worth being explicit about
why it is the AC round trip and not the more quotable one. The same plant's better-known
pair — 85 % at full power falling to 65 % at low power — is its *global* efficiency, whose
denominator includes auxiliary energy. Calibrating to that while separately charging
thermal load and no-load loss would count auxiliaries twice. It would also misattribute
the droop: on that plant a full cycle takes 26.4 hours at 0.1 p.u. against 2.6 hours at
rated, so most of the 85→65 fall is a near-constant auxiliary draw integrated over ten
times the exposure — a time integral, not part-load electronics, and not something that
belongs in a power-indexed curve.

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
| 2 | 0.00 MW | 25.03 MW | −5.9 % | +6.2 % |
| 5 | 39.53 MW | 43.43 MW | −18.7 % | +33.9 % |
| 10 | 46.98 MW | 47.50 MW | −11.6 % | +16.8 % |

![service-differentiated wear](figures/service_cdeg.png)

At £2/MW/h the single-cost model declines the reserve market outright — it holds no
reserve at all, because one degradation cost makes the availability payment look
uneconomic. The differentiated model commits 25 MW, because reserve duty is gentler on
the cells than arbitrage duty. That is a binary difference in whether the asset
participates, which no percentage change captures. Where both models participate the
capacity shift is modest, but cycling falls 6–19 % and net revenue rises 6–34 %
throughout.

**The threshold matters more than the headline.** Sweeping the ratio from 1.0 to 2.5
shows the market-entry flip happens between 1.5 and 1.85: at 1.5 the differentiated model
holds no reserve either, byte for byte identical to the single-cost model. That is
uncomfortable, because 1.5 is what the lifetime study implies and 1.85 is what the
throughput-normalised module test implies. **The flip therefore sits inside the range the
two corroborating studies span, not safely beyond it** — so the defensible claim is that
service differentiation *can* decide participation at plausible parameter values, not that
it does.

This finding also rests on the weakest assumption in the project, stated in the code:
mapping a capacity-loss ratio onto a marginal-cost ratio presumes damage accumulates
linearly with throughput, the approximation degradation physics is known to violate. Two
provenance caveats point the same way — the 220 Ah modules are second-life cells, and all
authors of that study are at one instrument manufacturer. The reserve price is the same
synthetic constant used in finding 2.

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
publicly reachable and need no key or registration (verified 2026-07-28); existing
Python wrappers for them are unmaintained, so the client is self-contained and caches to
parquet. One command reproduces every number above from nothing. No Elexon data is
redistributed here — the cache is git-ignored and each run fetches its own copy — and
Elexon's terms of use are not asserted in this repository; see NOTICE.

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
That paper also assesses its assumptions successively rather than only in aggregate, so
the decomposition itself is not what is new here. What differs is the shape of the
decomposition and, more usefully, a disagreement worth having: it assembles assumptions
cumulatively, so whichever enters first absorbs the largest share, whereas each assumption
here is isolated against a common baseline. **And the two studies reach opposite
conclusions on the same question** — it identifies part-load efficiency as the largest
error source, while finding 4 here concludes that the two halves of the flat-efficiency
error nearly cancel and the residue is auxiliary consumption. Two further dimensions enter
here that it does not cover, auxiliary load and forecast skill, and the market is GB
wholesale rather than continental day-ahead plus FCR. Anyone reading this repo as novel
should read that paper first.

On the individual layers:

| published work | what it establishes | how this differs |
|---|---|---|
| Kumtepeli et al. (2024), ACC, doi:10.23919/ACC60939.2024.10644173 | depreciation cost is a poor proxy for revenue lost to ageing; profit 30–50 % below the best-parameterised case | measures the error in *reported revenue*, not the loss from a suboptimal dispatch rule |
| Jafari, Botterud & Sakti (2020), Applied Energy 276, 115417 | simplified battery representations overstate offshore wind-storage revenue by ~35 % | GB standalone asset on 2024–2025 data; overstatement split into attributable layers rather than one total |
| Falezza (2026), arXiv:2604.12082 | forecast skill maps non-linearly to revenue; Kendall τ, not MAE, is the decision-relevant axis; persistence captures 32.8 % of oracle | see the reconciliation below |
| Humiston, Cetin & de Queiroz (2026), Energies 19(4) 1056 | linear-calendar and energy-throughput ageing give ≈2 %/yr and modest economic impact; rainflow gives much higher loss, large negative valuation, and is highly sensitive to calibration | that calibration sensitivity is the failure mode field anchoring here is built to avoid; their design deliberately holds dispatch fixed, whereas dispatch response is the object of study here |
| Cornejo et al. (2025), ISGT Europe, doi:10.1109/ISGTEurope64741.2025.11305340 | putting a non-linear equivalent-circuit loss model inside an MPC is worth 0.4 / 1.9 / 3.8 % at internal-resistance multipliers of 1 / 2 / 3 | the comparable fresh-asset figure there is 0.4 %, against 4.2–4.8 % here; the gap is the calibration basis, not the mechanism (see Status). Those three percentages are read from the preprint and have not been checked against the published version |
| Gatta et al. (2015), IEEE PowerTech, doi:10.1109/PTC.2015.7232464 | auxiliary loads are "usually disregarded in studies concerning BESS integration" | supplies the prevalence evidence for finding 4 rather than asserting it |
| Schimpe et al. (2018), Applied Energy 210, 211–229 | 18 loss mechanisms in a container system; power-electronic losses exceed cell losses at low operating power | the mechanism behind the curve shape used here |
| Gale et al. (2026), J. Energy Storage 166, 122328 | GB balancing-market access is worth £166,123/MW/yr against £47,234/MW/yr for wholesale alone — but the first figure assumes unconstrained BM access, and the paper notes real batteries skip over 90 % of instructions and that a commercial GB battery earned £101k/MW/yr from all sources in 2023; revenue falls about £12,000/MW/yr per 10 points of skip rate | the sharpest disagreement in this table, and the best prevalence evidence for finding 1: it prices wear at £0.50/MWh and argues explicitly that "the insensitivity of results to our economic proxy for degradation lends support to not needing to model degradation" — a 2026, GB, open-access paper taking the exact shortcut finding 1 measures, at 1/61 of the cost used here. Its wholesale-only figure is also the closest published like-for-like revenue comparison, used as such below |
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

**On prevalence, and where the claim is weak.** Most of the table above prices
degradation, which is evidence *against* the composite baseline being universal. The one
unambiguous contemporary instance is Gale et al. (2026): same market, same year, open
access, wear priced at £0.50/MWh with an explicit argument that detailed degradation
modelling is unnecessary. Auxiliary omission has a clean source in Gatta et al., who
record that auxiliary loads are "usually disregarded". Beyond those, "common" rests on
Mohamed et al.'s opening characterisation and Vykhodtsev et al.'s taxonomy, not on a
census — so the claim is strongest for degradation and auxiliaries and weakest for the
composite baseline as a whole. Worth adding that Gale et al.'s own numbers do not fully
support their insensitivity claim: raising their proxy from £0.50 to £5/MWh costs about
£25,000/MW/yr, roughly 15 % of their headline stack.

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
| this project, degradation ignored, perfect foresight | 45,295 | wholesale arbitrage only |
| **Gale et al. (2026), modelled, wholesale only, 100 MW / 1 h, June 2020 – June 2023** | **47,234** | wholesale arbitrage only, marginal cost £0.5/MWh |
| this project, field-anchored degradation, perfect foresight | 19,370 | wholesale arbitrage only |
| this project, degradation + out-of-sample forecast | 4,142 | wholesale arbitrage only |
| Modo Energy, realised, typical 2 h GB BESS, 12 months to Apr 2026 — wholesale + balancing only | 43,829 | 60 % of that fleet's stack |
| Modo Energy, same asset and period, **full stack** | 73,145 | + Capacity Market (7,454) + ancillary (33 % gross) |
| Gale et al. citing Modo: a real commercial GB battery, all sources, Jan–Aug 2023 | ~101,000 | full stack |

The top line is the closest like-for-like comparison: wholesale arbitrage, before
degradation is priced, on a perfect-foresight schedule, over the full window. At £45.3k
against £47.2k the two land within 4 % — but that agreement should not be leaned on,
because one adjustment is known and unapplied. Gale et al. model a one-hour asset and
state that doubling energy capacity raises revenue by about 30 %, which puts their figure
nearer £61k on a two-hour basis; on that correction this project sits about a quarter
below them, on a different three-year window that included the 2022 price crisis. The
honest reading is *the same order of magnitude, with the duration correction unresolved*.

**What the comparison does establish is that the apparent order-of-magnitude discrepancy
against full-stack indices is not a modelling error.** It is the deductions this project
measures plus the markets it excludes. Reading down the table: pricing wear at the
field-anchored £30.56/MWh cuts the figure by 57 %, and replacing foresight with a real
out-of-sample forecast removes four fifths of what is left. Neither step is present in any
published index.

What is excluded is as important. This asset trades one price series. It does not touch
the Balancing Mechanism, holds no ancillary contracts, and earns no Capacity Market
derating payment — the last of which alone is £7,454/MW/yr in the Modo breakdown.
Consistent with that, `v1` shows a single reserve stream at £5–10/MW/h lifting net revenue
to £40k–£81k/MW/yr, which brackets the £73k full-stack benchmark.

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

Two properties of the suite are worth naming because they are uncommon. The headroom
check is bidirectional: it asserts not only that reserve is deliverable when the constraint
is on, but that it is *demonstrably undeliverable* when the constraint is off — otherwise
the experiment might be measuring nothing. And the degradation checks assert the closed
form the cost reduces to, which is what catches a scaling factor silently cancelling the
model it is meant to scale.

What the suite does not yet cover is the rolling-horizon backtest path that produces the
headline numbers: window-to-window state-of-charge carry-over, the separation of forecast
from realised prices, and the settlement-side auxiliary deductions all run through
`run_backtest`, which no check touches. Nor is any published number pinned against
regression. Both gaps are real and known.

Every substantive error found in this project so far was caught the same way, and it is
worth stating because it is the working method rather than an anecdote: not by reading the
code, which was internally consistent throughout, but by asking whether a quantity was the
right *size*, and whether a cited number meant what the citation implied. An auxiliary
consumption of a quarter of throughput against a field range of 1–3 % is an order-of-
magnitude error visible without any debugging. Two efficiency metrics in the same paper
differing only by auxiliary energy is a definition error visible only by reading the
paper's equations rather than its abstract. A scaling factor that made two cell models
with an 11.6× difference return identical costs is visible only by evaluating both.

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
for putting a non-linear loss model inside the optimiser is 0.4 %, against 4.2–4.8 %
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

**Market data.** Elexon Insights / BMRS (no API key required). Third-party licence
terms, including the BSD-3-Clause notice for the degradation parameters, are in NOTICE.

Every reference above was checked against Crossref or publisher metadata rather than
carried over from memory; where only an abstract could be read, the section that cites it
says so.
