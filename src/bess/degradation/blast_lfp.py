"""
Semi-empirical LFP degradation, parameterised from NREL BLAST-Lite.

Two cell models are implemented because they disagree, and the disagreement is
itself part of the answer:

  sony_murata_3ah   Sony/Murata LFP-Gr 3 Ah cylindrical, fitted by NREL to the
                    data of Naumann et al. (J. Energy Storage 17, 2018,
                    doi:10.1016/j.est.2018.01.019; J. Power Sources 451, 2020,
                    doi:10.1016/j.jpowsour.2019.227666). Wide DoD coverage.
                    NREL refitted all parameters on the full dataset rather than
                    reproducing Naumann's 5-parameter form, so this is "Naumann's
                    data, NREL's fit" and must be cited as such.

  prismatic_250ah   Large-format prismatic LFP >250 Ah, 6 h energy-to-power —
                    i.e. the format actually deployed in grid storage. Fitted by
                    NREL in Gasper et al. (J. Energy Storage, 2023,
                    doi:10.1016/j.est.2023.109042).
                    Validity limits stated in the source: DoD 0.8-1.0, 10-45 degC,
                    charge <= 0.65 C, discharge <= 1.0 C. Shallow cycling is an
                    extrapolation and is flagged, not silently allowed.

Neither model is a system-level (container) degradation model: no such public
dataset exists. Field evidence puts whole-system loss at roughly 1.4-3 %/yr
(Italian utility-scale BESS 1.37 %/yr, doi:10.1016/j.est.2023.107232; EPRI
third-party measurement ~2.3 %/yr; 21 German household systems over 8 years
2-3 %/yr, doi:10.5281/zenodo.12091223). Cell-level models are used here for the
*shape* of the response to operating conditions, and the field range is used for
the *level*, via calibrate_to_field().
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field

import numpy as np

R_GAS = 8.3144  # J/mol/K


def _ua_from_soc(soc):
    """Negative-electrode equilibrium potential vs Li/Li+ (V), graphite.

    Piecewise fit used by BLAST-Lite for LFP-Gr cells; Ua enters the calendar
    ageing term. Kept explicit rather than hidden in a lookup so the reader can
    see what is being assumed.
    """
    soc = np.clip(np.asarray(soc, dtype=float), 0.0, 1.0)
    return 0.6379 + 0.5416 * np.exp(-305.5309 * soc) \
        + 0.044 * np.tanh(-(soc - 0.1958) / 0.1088) \
        - 0.1978 * np.tanh((soc - 1.0571) / 0.0854) \
        - 0.6875 * np.tanh((soc + 0.0117) / 0.0529) \
        - 0.0175 * np.tanh((soc - 0.5692) / 0.0875)


@dataclass
class SonyMurata3Ah:
    """BLAST-Lite lfp_gr_SonyMurata3Ah_2018."""
    name: str = "sony_murata_3ah"
    dod_valid: tuple = (0.0, 1.0)

    q1_b0: float = 0.989687151293590
    q1_b1: float = -2881067.56019324
    q1_b2: float = 8742.06309157261
    q5_b0: float = -6.81260579372875e-06
    q5_b1: float = 2.59615973160844e-05
    q5_b2: float = 2.11559710307295e-06

    def calendar_rate(self, t_kelvin, soc):
        """Rate parameter of the calendar term. NOT a capacity loss per unit time.

        Upstream evolves calendar fade with a sigmoid state update in which this value
        is the rate constant, so it cannot be multiplied by time — or by any power of
        time — to obtain a loss. Doing so gives several hundred per cent per year. The
        sigmoid is not implemented here, which is why cumulative_loss below refuses to
        run for this model.
        """
        ua = _ua_from_soc(soc)
        return abs(self.q1_b0
                   * np.exp(self.q1_b1 * (1.0 / t_kelvin ** 2) * np.sqrt(np.abs(ua)))
                   * np.exp(self.q1_b2 * (1.0 / t_kelvin) * np.sqrt(np.abs(ua))))

    def cycle_rate(self, dod, c_rate):
        """Fractional capacity loss per equivalent full cycle."""
        dod = np.clip(np.asarray(dod, dtype=float), 1e-6, 1.0)
        c_rate = np.asarray(c_rate, dtype=float)
        return abs(self.q5_b0 + self.q5_b1 * dod
                   + self.q5_b2 * np.exp(np.clip(dod ** 2 * c_rate ** 3, None, 50.0)))

    # Upstream applies no power-law exponent to this model's cycle term, so throughput
    # ageing is linear here. The calendar term has no usable exponent at all: see
    # calendar_rate.
    p_cal: float = float("nan")
    p_cyc: float = 1.0

    def cumulative_loss(self, t_days, n_efc, t_kelvin=298.15, soc=0.5, dod=0.9, c_rate=0.5):
        raise NotImplementedError(
            "the calendar term of the Sony/Murata model is a sigmoid state update "
            "upstream and is not implemented here, so total loss cannot be formed and "
            "this model cannot be field-anchored. Its cycle term is usable on its own "
            "via cycle_rate/marginal_cycle_loss; prismatic_250ah is the anchored default.")

    def marginal_cycle_loss(self, n_efc, dod=0.9, c_rate=0.5, t_kelvin=298.15):
        """d(loss)/d(cycle) at n_efc cycles already accumulated."""
        n = max(float(n_efc), 1.0)
        return float(self.p_cyc * self.cycle_rate(dod, c_rate) * n ** (self.p_cyc - 1.0))


@dataclass
class Prismatic250Ah:
    """BLAST-Lite lfp_gr_250AhPrismatic_2019 (Gasper et al. 2023)."""
    name: str = "prismatic_250ah"
    dod_valid: tuple = (0.8, 1.0)          # stated validity, enforced by warn_out_of_range
    temp_valid: tuple = (283.15, 318.15)

    p1: float = 8.37e04
    p2: float = -5.21e03
    p3: float = -3.56e03
    p_cal: float = 0.526
    p4: float = 4.38e-08
    p5: float = 1.55e-08
    p6: float = 1.68e-07
    p7: float = 2.19e03
    p8: float = 1.55e05
    p_cyc: float = 0.828

    def calendar_rate(self, t_kelvin, soc):
        ua = _ua_from_soc(soc)
        return abs(self.p1) * np.exp(self.p2 / t_kelvin) * np.exp(self.p3 * ua / t_kelvin)

    def cycle_rate(self, dod, c_rate, t_kelvin=298.15):
        dod = np.clip(np.asarray(dod, dtype=float), 1e-6, 1.0)
        return (self.p4 + self.p5 * dod + self.p6 * np.asarray(c_rate, dtype=float)) \
            * (np.exp(self.p7 / t_kelvin) + np.exp(-self.p8 / t_kelvin))

    def cumulative_loss(self, t_days, n_efc, t_kelvin=298.15, soc=0.5, dod=0.9, c_rate=0.5):
        """Capacity lost after t_days of storage and n_efc equivalent full cycles.

        Both terms are power laws, not linear rates. Treating the coefficients as
        per-day and per-cycle losses — which an earlier version did, because the
        exponents were declared and then never used — overstates three years of this
        plant's degradation by a factor of sixteen, and was what made field anchoring
        look mandatory rather than a modest correction.
        """
        return (self.calendar_rate(t_kelvin, soc) * np.power(t_days, self.p_cal)
                + self.cycle_rate(dod, c_rate, t_kelvin) * np.power(n_efc, self.p_cyc))

    def marginal_cycle_loss(self, n_efc, dod=0.9, c_rate=0.5, t_kelvin=298.15):
        """d(loss)/d(cycle) at n_efc cycles already accumulated.

        This, not the coefficient, is what a degradation *cost* per MWh needs: the
        wear caused by one more cycle. Because the exponent is below one it falls as
        the asset ages, so c_deg is not a constant.
        """
        n = max(float(n_efc), 1.0)
        return float(self.p_cyc * self.cycle_rate(dod, c_rate, t_kelvin)
                     * n ** (self.p_cyc - 1.0))

    def warn_out_of_range(self, dod=None, t_kelvin=None):
        """Return the stated validity violations at this operating point.

        This used to exist without ever being called, while the module docstring
        claimed shallow cycling was "flagged, not silently allowed". It is now called
        from DegradationCost, because a validity limit nothing consults is decoration.
        """
        out = []
        if dod is not None:
            lo, hi = self.dod_valid
            if float(np.min(dod)) < lo or float(np.max(dod)) > hi:
                out.append(f"depth of discharge {float(np.min(dod)):.2f}-{float(np.max(dod)):.2f} "
                           f"outside the fitted range {lo:.2f}-{hi:.2f}")
        if t_kelvin is not None and hasattr(self, "temp_valid"):
            lo, hi = self.temp_valid
            if not (lo <= float(t_kelvin) <= hi):
                out.append(f"temperature {float(t_kelvin)-273.15:.0f} degC outside the fitted "
                           f"range {lo-273.15:.0f}-{hi-273.15:.0f} degC")
        return out


MODELS = {"sony_murata_3ah": SonyMurata3Ah, "prismatic_250ah": Prismatic250Ah}


@dataclass
class DegradationCost:
    """Throughput-linear marginal degradation cost, c_deg (currency per MWh).

    The optimiser needs a linear penalty, so cycle degradation is collapsed to a
    cost per MWh of throughput:

        c_deg = replacement_cost_per_MWh * loss_per_EFC / usable_fraction_at_EOL

    Two refinements over the usual constant are supported, because both change
    dispatch:

    service_multiplier
        Peak-shifting (deep, energy-arbitrage cycling) ages a cell roughly 1.8-1.9x
        faster than frequency regulation at equal throughput, measured on 220 Ah
        LFP modules under real grid duty profiles (Xu et al., Frontiers in Energy
        Research 13, 1528691, 2025, doi:10.3389/fenrg.2025.1528691: 1.81 at 25 degC,
        1.92 at 40 degC, as a ratio of state-of-health-versus-throughput fit slopes).
        Only the *ratio* is portable; the absolute loss percentages come from an
        accelerated test and are not annual field rates. Two provenance caveats that
        argue for sweeping rather than trusting the value: the modules are BYD
        "gradient utilization" cells, i.e. second-life, and all authors are at a
        single instrument manufacturer.
        The direction is corroborated independently on a different chemistry.
        Ohrelius et al. cycled NMC532/graphite 18650 cells at 40 degC under five grid
        duty profiles and report "a slower trend for FR and a faster rate for PS",
        attributing the difference to state-of-charge swing amplitude rather than
        C-rate (J. Electrochem. Soc. 171(12) 120501, 2024,
        doi:10.1149/1945-7111/ad92db); the same group's service-lifetime study puts
        frequency regulation at 12 years against 8 for peak shifting, a ratio near
        1.5 (Energies 16(7) 3003, 2023, doi:10.3390/en16073003). Two chemistries and
        two measurement conventions agree on the sign and bracket the magnitude,
        which is why the sweep runs 1.0-2.5 rather than stopping at 1.85.
        Note the assumption this carries: mapping a capacity-loss ratio onto a
        marginal-cost ratio presumes damage is proportional to throughput, which
        is exactly the linear-accumulation approximation (Miner's rule) that
        degradation physics is known to violate. Treated here as an explicit
        assumption with a sensitivity switch, not as a fact.

    discount_rate
        Replacement happens in the future, so its present value is lower and early
        cycling should be priced below nameplate. c_deg is scaled by the discount
        factor at the expected replacement year.
    """
    replacement_cost_per_mwh: float = 120_000.0   # GBP/MWh installed, order of magnitude
    eol_fraction: float = 0.8                     # end of life at 80 % capacity
    cell_model: str = "prismatic_250ah"
    discount_rate: float = 0.08
    expected_life_years: float = 12.0
    # Relative ageing per MWh of throughput between services, normalised so that
    # the anchoring reference service is 1.0. Anchoring is done against observed
    # field loss from mixed real operation, so applying a raw >1 multiplier on top
    # would double-count: the field rate already contains whatever service mix
    # those systems ran. Ratios are therefore expressed relative to the reference.
    service_multiplier: dict = field(default_factory=lambda: {"arbitrage": 1.85, "frequency": 1.0})
    anchor_reference_service: str = "arbitrage"
    # Field anchoring: cell models supply the response shape, observed
    # system-level loss supplies the level. Raw cell models over-predict here
    # (both give >5 %/yr at 300 EFC/yr against a 1.4-3 %/yr field range), so
    # running them unscaled would price degradation above realistic spreads and
    # silently suppress all trading.
    field_annual_loss: float | None = 0.0137      # None disables anchoring
    field_efc_per_year: float = 118.7
    field_years: float = 3.0
    # Anchoring needs a *pair*: a loss rate is meaningless without the cycling that
    # produced it. Only one public field case reports both — the Italian utility-scale
    # plant, 356 equivalent full cycles over three years to 95.88 %% state of health,
    # i.e. 118.7 EFC/yr at 1.37 %%/yr (doi:10.1016/j.est.2023.107232). The German and
    # EPRI cases give a loss rate without a cycle count, so using them requires an
    # assumed EFC and is treated as sensitivity rather than calibration.
    #
    # The anchor scales the whole model — calendar and cycle together — so that its
    # predicted loss over the field plant's own life matches what was measured. With
    # the power laws applied that scale is about 0.83, i.e. the cell model very nearly
    # reproduces a system it was never fitted to. An earlier version divided the field's
    # *total* loss by a *cycle-only* model term, which charged calendar ageing to the
    # marginal cycle and inflated c_deg roughly threefold. Calendar fade happens whether
    # or not the asset trades, so it is a cost of ownership, not of throughput.
    #
    # Chemistry caveat that anchoring cannot remove: the field plant is NMC, the cell
    # models are LFP. The anchor transfers a level between chemistries that age at
    # different rates and with different calendar-to-cycle splits.
    reference_cycles: float = 1000.0
    # c_deg is the marginal wear of one more cycle, and the cycle exponent is below one,
    # so it declines over life: about 15.4 GBP/MWh at 250 cumulative cycles and 10.0 at
    # 3000. A single number has to name a point on that curve; 1000 EFC is roughly
    # mid-life for an asset cycling a few hundred times a year, and v0 sweeps it.
    #
    # What the anchor does *not* do is make c_deg a measured quantity. It is
    #     replacement_cost * discount_factor * marginal_loss / usable / dod
    # and only the field pair inside marginal_loss is observed. The other inputs are
    # conventions, and the result is sensitive to them: sweeping the discount rate over
    # 0-12 %% moves c_deg by roughly a factor of four, replacement cost over 80-160 k/MWh
    # by a factor of two, assumed life over 8-15 years by a factor of 1.7.

    def _model(self):
        return MODELS[self.cell_model]()

    def loss_per_efc(self, dod: float = 0.9, c_rate: float = 0.5, t_kelvin: float = 298.15,
                     n_efc: float | None = None) -> float:
        """Marginal capacity loss of one more equivalent full cycle, unanchored."""
        n = self.reference_cycles if n_efc is None else n_efc
        m = self._model()
        if hasattr(m, "warn_out_of_range"):
            for msg in m.warn_out_of_range(dod=dod, t_kelvin=t_kelvin):
                warnings.warn(f"{self.cell_model}: {msg}; the result is an extrapolation",
                              RuntimeWarning, stacklevel=2)
        return float(m.marginal_cycle_loss(n, dod=dod, c_rate=c_rate, t_kelvin=t_kelvin))

    # Operating point the field anchor is defined at. The anchor must be computed
    # here and nowhere else: an earlier version evaluated it at the caller's depth
    # of discharge, so the cell model's loss term appeared in the numerator and the
    # denominator at the same depth and cancelled exactly.
    REF_DOD, REF_C_RATE, REF_T_KELVIN = 0.9, 0.5, 298.15

    def anchor_factor(self) -> float:
        """Scale reconciling the cell model with the field plant's observed loss.

        Compares like with like: total modelled loss (calendar plus cycle) over the
        field plant's own duration and cycle count, against its measured total loss.
        """
        if self.field_annual_loss is None:
            return 1.0
        days = self.field_years * 365.25
        n = self.field_efc_per_year * self.field_years
        modelled = float(self._model().cumulative_loss(
            days, n, t_kelvin=self.REF_T_KELVIN, soc=0.5,
            dod=self.REF_DOD, c_rate=self.REF_C_RATE))
        observed = self.field_annual_loss * self.field_years
        return float(observed / max(modelled, 1e-12))

    def implied_cycle_life(self) -> float:
        """Equivalent full cycles to end of life from cycling alone, as a sanity check.

        A value far outside the 4000-10000 that large-format LFP is warranted for means
        the parameterisation is wrong, and that is how the missing exponents surfaced.
        """
        m = self._model()
        k = float(m.cycle_rate(self.REF_DOD, self.REF_C_RATE, self.REF_T_KELVIN)
                  if self.cell_model == "prismatic_250ah"
                  else m.cycle_rate(self.REF_DOD, self.REF_C_RATE)) * self.anchor_factor()
        return float(((1.0 - self.eol_fraction) / k) ** (1.0 / m.p_cyc))

    def base_cost(self, dod: float = 0.9, c_rate: float = 0.5, t_kelvin: float = 298.15,
                  n_efc: float | None = None) -> float:
        """c_deg in currency per MWh of throughput, before service differentiation."""
        loss = self.loss_per_efc(dod, c_rate, t_kelvin, n_efc) * self.anchor_factor()
        usable = 1.0 - self.eol_fraction
        disc = 1.0 / (1.0 + self.discount_rate) ** self.expected_life_years
        # cost of consuming `loss` of the usable life, per full cycle, spread over
        # the energy moved in that cycle (dod fraction of nameplate, per MWh)
        return self.replacement_cost_per_mwh * disc * loss / usable / max(dod, 1e-6)

    def cost(self, service: str = "arbitrage", **kw) -> float:
        """c_deg for a service, normalised to the anchoring reference.

        base_cost() already reproduces the observed field loss for the reference
        service; other services are priced by their *ratio* to it, so the level is
        set once by field evidence and the differentiation is set by the module
        experiment (Frontiers 2025 PS/FR = 1.81-1.92).
        """
        ref = self.service_multiplier.get(self.anchor_reference_service, 1.0)
        return self.base_cost(**kw) * self.service_multiplier.get(service, 1.0) / ref


def calibrate_to_field(cost: DegradationCost, target_annual_loss: float,
                       efc_per_year: float, dod: float = 0.9) -> float:
    """Scale factor that makes the cell model reproduce a field annual loss rate.

    Field evidence spans 1.4-3 %/yr at system level; running the backtest at both
    ends of that range is the honest alternative to pretending one number is known.
    Returns the multiplicative factor applied to loss_per_efc.
    """
    modelled = cost.loss_per_efc(dod=dod) * efc_per_year
    return float(target_annual_loss / max(modelled, 1e-12))


if __name__ == "__main__":
    print("raw cell models (unanchored):")
    for name in MODELS:
        c = DegradationCost(cell_model=name, field_annual_loss=None)
        implied = c.loss_per_efc() * 300
        print(f"  {name:18s} loss/EFC = {c.loss_per_efc():.3e} -> implied {implied:.1%}/yr at 300 EFC"
              f" | c_deg arb {c.cost('arbitrage'):7.2f} freq {c.cost('frequency'):6.2f} GBP/MWh")
    print("\nfield-anchored (level from observed 1.4-3 %/yr, shape from cell model):")
    for name in MODELS:
        for tgt in (0.014, 0.02, 0.03):
            c = DegradationCost(cell_model=name, field_annual_loss=tgt)
            print(f"  {name:18s} {tgt:.1%}/yr -> c_deg arb {c.cost('arbitrage'):6.2f}"
                  f" freq {c.cost('frequency'):6.2f} GBP/MWh (factor {c.anchor_factor():.2f})")
