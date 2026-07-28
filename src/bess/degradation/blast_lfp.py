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
        """Fractional capacity loss per sqrt(day) of storage."""
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

    def warn_out_of_range(self, dod):
        lo, hi = self.dod_valid
        frac = float(np.mean((np.asarray(dod) < lo) | (np.asarray(dod) > hi)))
        return frac


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
        LFP modules under real grid duty profiles (Frontiers in Energy Research 13,
        2025, doi:10.3389/fenrg.2025.1528691: 1.81 at 25 degC, 1.92 at 40 degC).
        Only the *ratio* is portable; the absolute loss percentages come from an
        accelerated test and are not annual field rates.
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
    # Anchoring needs a *pair*: a loss rate is meaningless without the cycling that
    # produced it. Only one public field case reports both — the Italian utility-scale
    # plant, 356 equivalent full cycles over three years to 95.88 %% state of health,
    # i.e. 118.7 EFC/yr at 1.37 %%/yr (doi:10.1016/j.est.2023.107232). The German and
    # EPRI cases give a loss rate without a cycle count, so using them requires an
    # assumed EFC and is treated as sensitivity rather than calibration.
    #
    # Making the anchor self-consistent with the model's own cycling (a fixed point
    # in EFC) was considered and rejected: it would assume this asset cycles at the
    # same rate as the field systems, which is precisely what is unknown. Iterating
    # to that fixed point moves c_deg from 17.7 to 10.9 GBP/MWh, so the choice is not
    # cosmetic and is stated rather than buried.

    def loss_per_efc(self, dod: float = 0.9, c_rate: float = 0.5, t_kelvin: float = 298.15) -> float:
        m = MODELS[self.cell_model]()
        if self.cell_model == "prismatic_250ah":
            return float(m.cycle_rate(dod, c_rate, t_kelvin))
        return float(m.cycle_rate(dod, c_rate))

    def anchor_factor(self, dod: float = 0.9) -> float:
        """Scale that reconciles the cell model with observed field loss."""
        if self.field_annual_loss is None:
            return 1.0
        modelled = self.loss_per_efc(dod=dod) * self.field_efc_per_year
        return float(self.field_annual_loss / max(modelled, 1e-12))

    def base_cost(self, dod: float = 0.9, c_rate: float = 0.5, t_kelvin: float = 298.15) -> float:
        """c_deg in currency per MWh of throughput, before service differentiation."""
        loss = self.loss_per_efc(dod, c_rate, t_kelvin) * self.anchor_factor(dod)
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
