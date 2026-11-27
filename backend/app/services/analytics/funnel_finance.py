"""Motor financiero determinístico por rangos (min, probable, max), punto de equilibrio y proyección 24m."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

import numpy as np

from country_packs import get_country_pack


@dataclass
class RangeEstimate:
    min: float
    probable: float
    max: float
    unit: str

    def __post_init__(self):
        ordered = sorted([float(self.min), float(self.probable), float(self.max)])
        self.min, self.probable, self.max = ordered[0], ordered[1], ordered[2]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class FunnelFinanceEngine:
    """Modela economía unitaria, punto de equilibrio y proyección a 24 meses sin inventar certezas puntuales."""

    SCENARIOS = [
        {"name": "conservador", "probability_pct": 30.0, "cpl_mult": 1.35, "conv_mult": 0.65, "growth_monthly": 0.06},
        {"name": "base", "probability_pct": 50.0, "cpl_mult": 1.00, "conv_mult": 1.00, "growth_monthly": 0.11},
        {"name": "optimista", "probability_pct": 20.0, "cpl_mult": 0.80, "conv_mult": 1.30, "growth_monthly": 0.16},
    ]

    def analyze(
        self,
        country_code: str = "co",
        optimal_price_a: Optional[float] = None,
        conversion_rate_probable: float = 0.08,
        fixed_monthly_opex_cop: float = 4_200_000.0,
        unit_label: str = "transacciones/mes",
        unit_var_cost_cop: Optional[float] = None,
        upsell_offer: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        pack = get_country_pack(country_code or "co")
        currency = pack.currency
        ticket_a_prob = float(optimal_price_a) if optimal_price_a and optimal_price_a > 0 else 50_000.0

        # Escalar CPL según escala de ticket del proyecto (micro-comercio vs B2C vs B2B)
        if ticket_a_prob < 20_000:
            cpl = RangeEstimate(min=800.0, probable=1_800.0, max=3_500.0, unit=currency)
        elif ticket_a_prob > 250_000:
            cpl = RangeEstimate(min=18_000.0, probable=38_000.0, max=75_000.0, unit=currency)
        else:
            cpl = RangeEstimate(min=4_500.0, probable=8_500.0, max=16_000.0, unit=currency)

        conv = RangeEstimate(
            min=max(0.02, round(conversion_rate_probable * 0.55, 4)),
            probable=max(0.03, round(conversion_rate_probable, 4)),
            max=min(0.45, round(conversion_rate_probable * 1.55, 4)),
            unit="ratio",
        )
        cpa = RangeEstimate(
            min=round(cpl.min / conv.max, 2),
            probable=round(cpl.probable / conv.probable, 2),
            max=round(cpl.max / conv.min, 2),
            unit=currency,
        )
        ticket_a = RangeEstimate(
            min=round(ticket_a_prob * 0.75, 2),
            probable=round(ticket_a_prob, 2),
            max=round(ticket_a_prob * 1.40, 2),
            unit=currency,
        )
        vc_prob = float(unit_var_cost_cop) if unit_var_cost_cop and unit_var_cost_cop > 0 else round(ticket_a_prob * 0.35, 2)
        var_cost_a = RangeEstimate(
            min=round(vc_prob * 0.65, 2),
            probable=round(vc_prob, 2),
            max=round(vc_prob * 1.45, 2),
            unit=currency,
        )

        upsell_price = float((upsell_offer or {}).get("price_cop") or round(ticket_a_prob * 2.5, 2))
        upsell_var_cost = round(upsell_price * 0.35, 2)
        upsell_margin = max(0.0, upsell_price - upsell_var_cost)
        attach_rate = 0.18 if upsell_offer else 0.12

        blended_margin_prob = max(
            100.0,
            (ticket_a.probable - var_cost_a.probable) + attach_rate * upsell_margin - cpa.probable * 0.25,
        )
        contrib_margin = RangeEstimate(
            min=max(50.0, round((ticket_a.min - var_cost_a.max) + (attach_rate * 0.5) * upsell_margin, 2)),
            probable=round(blended_margin_prob, 2),
            max=round((ticket_a.max - var_cost_a.min) + (attach_rate * 1.5) * upsell_margin, 2),
            unit=currency,
        )

        fixed_opex = RangeEstimate(
            min=round(fixed_monthly_opex_cop * 0.80, 2),
            probable=float(fixed_monthly_opex_cop),
            max=round(fixed_monthly_opex_cop * 1.35, 2),
            unit=currency,
        )

        # Punto de equilibrio en la unidad del negocio
        clean_unit = unit_label or "transacciones/mes"
        be_cases_prob = math.ceil(fixed_opex.probable / max(100.0, contrib_margin.probable))
        be_cases_min = math.ceil(fixed_opex.min / max(100.0, contrib_margin.max))
        be_cases_max = math.ceil(fixed_opex.max / max(100.0, contrib_margin.min))
        break_even_cases = RangeEstimate(min=be_cases_min, probable=be_cases_prob, max=be_cases_max, unit=clean_unit)

        base_leads_m1 = 220 if ticket_a_prob < 20_000 else (80 if ticket_a_prob > 250_000 else 180)
        monthly_rows: List[Dict[str, Any]] = []
        quarterly_rows: List[Dict[str, Any]] = []
        cum_cash = 0.0
        break_even_month: Optional[int] = None

        scenario_summaries: List[Dict[str, Any]] = []
        for sc in self.SCENARIOS:
            sc_cum = 0.0
            sc_cases_24m = 0
            sc_rev_24m = 0.0
            sc_be_month: Optional[int] = None
            sc_monthly_details: List[Dict[str, Any]] = []

            for m in range(1, 25):
                leads = int(round(base_leads_m1 * ((1.0 + sc["growth_monthly"]) ** (m - 1))))
                eff_conv = conv.probable * sc["conv_mult"]
                cases_a = int(round(leads * eff_conv))
                cases_b = int(round(cases_a * attach_rate))
                rev = cases_a * ticket_a.probable + cases_b * upsell_price
                mkt_spend = leads * (cpl.probable * sc["cpl_mult"])
                op_var = cases_a * var_cost_a.probable + cases_b * upsell_var_cost
                ebitda = rev - mkt_spend - op_var - fixed_opex.probable
                sc_cum += ebitda
                sc_cases_24m += cases_a
                sc_rev_24m += rev
                if sc_be_month is None and ebitda >= 0:
                    sc_be_month = m
                row = {
                    "month": m,
                    "leads": leads,
                    "cases_a": cases_a,
                    "cases_b": cases_b,
                    "revenue": round(rev, 2),
                    "marketing_spend": round(mkt_spend, 2),
                    "ebitda": round(ebitda, 2),
                    "cumulative_cash": round(sc_cum, 2),
                }
                sc_monthly_details.append(row)

            scenario_summaries.append(
                {
                    "scenario": sc["name"],
                    "probability_pct": sc["probability_pct"],
                    "total_cases_a_24m": sc_cases_24m,
                    "total_revenue_24m": round(sc_rev_24m, 2),
                    "ending_cumulative_cash": round(sc_cum, 2),
                    "break_even_month": sc_be_month,
                }
            )

            if sc["name"] == "base":
                monthly_rows = sc_monthly_details[:12]
                cum_cash = sc_cum
                break_even_month = sc_be_month
                for q_idx in range(4):
                    start_m = 12 + q_idx * 3
                    chunk = sc_monthly_details[start_m : start_m + 3]
                    quarterly_rows.append(
                        {
                            "quarter": f"Q{5 + q_idx} (M{start_m + 1}-M{start_m + 3})",
                            "leads": sum(x["leads"] for x in chunk),
                            "cases_a": sum(x["cases_a"] for x in chunk),
                            "cases_b": sum(x["cases_b"] for x in chunk),
                            "revenue": round(sum(x["revenue"] for x in chunk), 2),
                            "marketing_spend": round(sum(x["marketing_spend"] for x in chunk), 2),
                            "ebitda": round(sum(x["ebitda"] for x in chunk), 2),
                            "ending_cumulative_cash": chunk[-1]["cumulative_cash"],
                        }
                    )

        # Sensibilidad determinística (choques de riesgo)
        base_24m_cash = next(s["ending_cumulative_cash"] for s in scenario_summaries if s["scenario"] == "base")
        sensitivity = [
            {
                "shock_name": "conversión -30%",
                "impact_factor": 0.70,
                "estimated_24m_cash": round(base_24m_cash * 0.58 - 18_000_000.0, 2),
                "severity": "alta",
            },
            {
                "shock_name": "CPL +50%",
                "impact_factor": 1.50,
                "estimated_24m_cash": round(base_24m_cash - 22_500_000.0, 2),
                "severity": "media-alta",
            },
            {
                "shock_name": "estrés de complejidad operativa y cumplimiento",
                "impact_factor": 1.25,
                "estimated_24m_cash": round(base_24m_cash - 15_000_000.0, 2),
                "severity": "media",
            },
        ]

        regulatory_warnings = [
            {
                "code": "COL_CONSUMER_PROTECTION",
                "norm": "Ley 1480 de 2011 (Estatuto del Consumidor)",
                "warning": "Prohibida la publicidad engañosa o promesas no verificables; informar precios totales, comisiones, alcance, garantías y derecho de retracto de forma clara y por escrito.",
            },
            {
                "code": "COL_DATA_PROTECTION",
                "norm": "Ley Estatutaria 1581 de 2012 (Habeas Data)",
                "warning": "Autorización previa, expresa e informada del titular para el tratamiento de datos personales capturados por WhatsApp, formularios web o plataformas digitales.",
            },
            {
                "code": "COL_COMMERCIAL_FORMALIZATION",
                "norm": "Código de Comercio y Estatuto Tributario (NIT / RUT)",
                "warning": "Identificación comercial verificable (NIT visible), facturación o soporte formal de pago y términos y condiciones claros para mitigar desconfianza en el mercado colombiano.",
            },
            {
                "code": "COL_SECTOR_COMPLIANCE",
                "norm": "Cumplimiento Regulatorio Sectorial (SFC / SIC / Sector Aplicable)",
                "warning": "Validar requisitos específicos de la industria antes de escalar (ej. pasarelas de pago vigiladas si hay custodia de fondos de terceros, permisos sanitarios o habilitaciones profesionales).",
            },
        ]

        # LTV, CAC, Payback y Semáforo Financiero (V3 §11.4, V-07, V-08)
        monthly_repeat_rate = 1.6 if ticket_a_prob < 25_000 else (1.25 if attach_rate >= 0.15 else 1.0)
        expected_months_active = 6.0 if monthly_repeat_rate > 1.0 else 1.0
        first_order_mc = round(ticket_a.probable - var_cost_a.probable, 2)
        ltv_min = round(max(100.0, contrib_margin.min * max(1.0, expected_months_active * 0.65)), 2)
        ltv_prob = round(max(100.0, contrib_margin.probable * expected_months_active * monthly_repeat_rate * 0.75), 2)
        ltv_max = round(max(100.0, contrib_margin.max * expected_months_active * monthly_repeat_rate), 2)
        ltv_range = RangeEstimate(min=ltv_min, probable=ltv_prob, max=ltv_max, unit=currency)

        ltv_cac_prob = round(ltv_range.probable / max(1.0, cpa.probable), 2)
        ltv_cac_range = RangeEstimate(
            min=round(ltv_range.min / max(1.0, cpa.max), 2),
            probable=ltv_cac_prob,
            max=round(ltv_range.max / max(1.0, cpa.min), 2),
            unit="ratio",
        )
        monthly_mc_per_customer = max(1.0, contrib_margin.probable * monthly_repeat_rate)
        payback_months = RangeEstimate(
            min=round(cpa.min / max(1.0, contrib_margin.max * monthly_repeat_rate), 2),
            probable=round(cpa.probable / monthly_mc_per_customer, 2),
            max=round(cpa.max / max(1.0, contrib_margin.min), 2),
            unit="meses",
        )
        cac_exceeds_first_mc = cpa.probable > first_order_mc
        has_proven_recurrence = monthly_repeat_rate > 1.0
        if ltv_cac_prob >= 3.0 and payback_months.probable <= 12.0 and contrib_margin.probable > 0:
            financial_semaphore = "verde"
        elif ltv_cac_prob >= 1.0 and contrib_margin.probable > 0:
            financial_semaphore = "ambar"
        else:
            financial_semaphore = "rojo"

        # Tabla de conciliación precio -> mix -> ingreso por unidad -> CV -> MC (V3 §11.6, V-05)
        blended_rev_per_unit = round(ticket_a.probable + attach_rate * upsell_price, 2)
        blended_cv_per_unit = round(var_cost_a.probable + attach_rate * upsell_var_cost, 2)
        reconciliation_table = {
            "primary_price_cop": round(ticket_a.probable, 2),
            "upsell_attach_rate": attach_rate,
            "upsell_price_cop": round(upsell_price, 2),
            "blended_revenue_per_unit_cop": blended_rev_per_unit,
            "blended_variable_cost_per_unit_cop": blended_cv_per_unit,
            "contribution_margin_cop": round(contrib_margin.probable, 2),
            "mix_explanation": (
                f"Ingreso unitario combinado = oferta principal (COP {int(ticket_a.probable):,}) "
                f"+ {int(attach_rate * 100)}% de adopción en nivel extendido (COP {int(upsell_price):,})."
            ),
        }

        # Simulación Monte Carlo vectorizada (5,000 corridas, M1-M24, V3 §11.5, V-11)
        mc_runs = 5000
        rng = np.random.default_rng(42)
        cpl_samples = rng.triangular(cpl.min, cpl.probable, cpl.max, size=mc_runs)
        conv_samples = rng.triangular(conv.min, conv.probable, conv.max, size=mc_runs)
        growth_samples = rng.triangular(0.05, 0.11, 0.17, size=mc_runs)
        cum_cash_paths = np.zeros((mc_runs, 24), dtype=float)
        rev_24m_samples = np.zeros(mc_runs, dtype=float)
        be_month_samples = np.full(mc_runs, 99, dtype=int)

        running_cash = np.zeros(mc_runs, dtype=float)
        for m in range(1, 25):
            leads_m = base_leads_m1 * ((1.0 + growth_samples) ** (m - 1))
            cases_a_m = leads_m * conv_samples
            cases_b_m = cases_a_m * attach_rate
            rev_m = cases_a_m * ticket_a.probable + cases_b_m * upsell_price
            mkt_m = leads_m * cpl_samples
            var_m = cases_a_m * var_cost_a.probable + cases_b_m * upsell_var_cost
            ebitda_m = rev_m - mkt_m - var_m - fixed_opex.probable
            running_cash = running_cash + ebitda_m
            cum_cash_paths[:, m - 1] = running_cash
            rev_24m_samples += rev_m
            be_mask = (be_month_samples == 99) & (ebitda_m >= 0)
            be_month_samples[be_mask] = m

        ending_cash_arr = cum_cash_paths[:, -1]
        min_cash_p10 = float(np.percentile(np.min(cum_cash_paths, axis=1), 10))
        funding_need = round(max(0.0, -min_cash_p10) + 3.0 * fixed_opex.probable, 2)
        monte_carlo_summary = {
            "runs": mc_runs,
            "revenue_24m_percentiles": {
                "p10": round(float(np.percentile(rev_24m_samples, 10)), 2),
                "p50": round(float(np.percentile(rev_24m_samples, 50)), 2),
                "p90": round(float(np.percentile(rev_24m_samples, 90)), 2),
            },
            "ending_cash_percentiles": {
                "p10": round(float(np.percentile(ending_cash_arr, 10)), 2),
                "p50": round(float(np.percentile(ending_cash_arr, 50)), 2),
                "p90": round(float(np.percentile(ending_cash_arr, 90)), 2),
            },
            "prob_break_even_before_m24": round(float(np.mean(be_month_samples <= 24)), 4),
            "prob_negative_ending_cash": round(float(np.mean(ending_cash_arr < 0)), 4),
            "funding_need_cop": funding_need,
            "break_even_thresholds": {
                "max_viable_cpa_cop": round(ltv_range.probable / 1.5, 2),
                "min_viable_conversion_rate": round(cpl.probable / max(1.0, ltv_range.probable / 1.5), 4),
            },
        }

        return {
            "status": "ok",
            "currency": currency,
            "financial_semaphore": financial_semaphore,
            "cac_exceeds_first_margin": cac_exceeds_first_mc,
            "has_proven_recurrence": has_proven_recurrence,
            "reconciliation_table": reconciliation_table,
            "monte_carlo": monte_carlo_summary,
            "unit_economics_ranges": {
                "cpl": cpl.to_dict(),
                "conversion_rate": conv.to_dict(),
                "cpa": cpa.to_dict(),
                "ltv": ltv_range.to_dict(),
                "ltv_cac_ratio": ltv_cac_range.to_dict(),
                "payback_months": payback_months.to_dict(),
                "ticket_service_a": ticket_a.to_dict(),
                "variable_cost_service_a": var_cost_a.to_dict(),
                "contribution_margin_blended": contrib_margin.to_dict(),
                "fixed_monthly_opex": fixed_opex.to_dict(),
                "break_even_cases": break_even_cases.to_dict(),
                "break_even_cases_per_month": break_even_cases.to_dict(),
                "break_even_month_base": break_even_month,
            },
            "scenarios": scenario_summaries,
            "scenario_probabilities_sum_pct": sum(s["probability_pct"] for s in scenario_summaries),
            "projection_24m": {
                "monthly_m1_m12": monthly_rows,
                "monthly_m1_m24": sc_monthly_details if "sc_monthly_details" in locals() else monthly_rows,
                "quarterly_m13_m24": quarterly_rows,
                "base_ending_cumulative_cash": round(cum_cash, 2),
            },
            "sensitivity_analysis": sensitivity,
            "regulatory_and_legal_warnings": regulatory_warnings,
        }
