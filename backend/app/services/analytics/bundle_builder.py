"""Ensamblador del artefacto único inmutable `analytics_bundle.json` (capítulos 01..12 + ECharts)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .cx_and_polarization import CXAndPolarizationEngine
from .data_loader import DataLoader
from .funnel_and_cdj import FunnelAndCDJEngine
from .funnel_finance import FunnelFinanceEngine
from .pricing_econometrics import PricingEconometricsEngine
from .qualitative_coder import QualitativeCoder
from .weighting_and_stats import WeightingAndStatsEngine


class AnalyticsBundleBuilder:
    """Ejecuta todos los motores determinísticos y escribe `analytics_bundle.json`."""

    def build(
        self,
        simulation_id: str,
        sim_dir: Path,
        project_dir: Optional[Path] = None,
        country_code: str = "co",
        write_file: bool = True,
    ) -> Dict[str, Any]:
        sim_dir = Path(sim_dir)
        data = DataLoader().load(simulation_id=simulation_id, sim_dir=sim_dir, project_dir=project_dir)

        stats_out = WeightingAndStatsEngine(country_code=country_code).analyze(data.survey_responses)
        cx_out = CXAndPolarizationEngine().analyze(data.survey_responses, data.channel_events)
        pricing_out = PricingEconometricsEngine().analyze(data.survey_responses)
        funnel_out = FunnelAndCDJEngine().analyze(data)

        from ..study_context_builder import load_study_context
        from ..secondary_research import SecondaryResearchEngine
        study_ctx = load_study_context("", project_dir=project_dir) if project_dir else None
        secondary_out = SecondaryResearchEngine().run(
            study_context=study_ctx or {"project_name": simulation_id, "sector": "general", "geographic_scope": "Colombia"},
            quant_indicators=data.quant_indicators,
            project_dir=project_dir,
        )

        qual_out = QualitativeCoder().analyze(data)

        vw_opt = (pricing_out.get("van_westendorp") or {}).get("nms", {}).get("optimal_revenue_price")
        gg_opt = (pricing_out.get("gabor_granger") or {}).get("optimal_price")
        ref_p = (study_ctx or {}).get("reference_price_cop") or 50_000.0
        opt_price = gg_opt or vw_opt or ref_p
        conv_prob = max(0.04, funnel_out.get("overall_awareness_to_adoption") or 0.08)
        finance_out = FunnelFinanceEngine().analyze(
            country_code=country_code,
            optimal_price_a=opt_price,
            conversion_rate_probable=min(0.25, conv_prob),
            fixed_monthly_opex_cop=float((study_ctx or {}).get("monthly_opex_cop") or 4_200_000.0),
            unit_label=str((study_ctx or {}).get("unit_label") or "transacciones/mes"),
            unit_var_cost_cop=(study_ctx or {}).get("unit_var_cost_cop"),
            upsell_offer=(study_ctx or {}).get("upsell_offer"),
        )

        warnings = []
        if cx_out.get("sycophancy_warning"):
            warnings.append("ALERTA_SYCOPHANCY: >85% respuestas positivas o baja polarización (<0.15).")
        if (cx_out.get("bimodality") or {}).get("bimodal_alert"):
            warnings.append("ALERTA_BIMODALIDAD: Coeficiente de bimodalidad BC > 0.555.")
        if data.is_legacy:
            warnings.append("MODO_LEGADO: Simulación sin encuesta estructurada ni tablas multicanal v2.")
        for gap in data.data_gaps:
            warnings.append(f"VACIO_DATOS_OFICIAL: {gap.get('metric_key')} - {gap.get('reason')}")

        charts_spec = self._build_echarts_specs(pricing_out, funnel_out, finance_out, qual_out, study_ctx=study_ctx, cx=cx_out)

        chapter_slices = {
            "01": {"data_audit": data.audit.to_dict(), "warnings": warnings, "finance_summary": finance_out["unit_economics_ranges"]},
            "02": {"data_audit": data.audit.to_dict(), "weights_summary": stats_out.get("weights_summary"), "quant_indicators": data.quant_indicators[:12]},
            "03": {"quant_indicators": data.quant_indicators, "data_gaps": data.data_gaps},
            "04": {"crosstabs": stats_out.get("crosstabs"), "hypothesis_tests": stats_out.get("hypothesis_tests")},
            "05": {"cx": cx_out, "qualitative_top_codes": qual_out.get("codebook", [])[:4]},
            "06": {"pricing": pricing_out},
            "07": {"funnel_and_cdj": funnel_out, "wilson_high_nps": stats_out.get("wilson_high_nps_rate")},
            "08": {"codebook": qual_out.get("codebook"), "total_texts_indexed": qual_out.get("total_texts_indexed")},
            "09": {"finance": finance_out},
            "10": {"regulatory_and_legal_warnings": finance_out["regulatory_and_legal_warnings"], "sensitivity": finance_out["sensitivity_analysis"]},
            "11": {"scenarios": finance_out["scenarios"], "optimal_price": opt_price, "warnings": warnings},
            "12": {"data_audit": data.audit.to_dict(), "corpus_coverage_pct": qual_out.get("corpus_coverage_pct"), "hypothesis_tests": stats_out.get("hypothesis_tests")},
        }

        core_payload = {
            "simulation_id": simulation_id,
            "country_code": country_code,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_audit": data.audit.to_dict(),
            "weighting_and_stats": stats_out,
            "cx_and_polarization": cx_out,
            "pricing_econometrics": pricing_out,
            "funnel_and_cdj": funnel_out,
            "funnel_finance": finance_out,
            "qualitative_coding": qual_out,
            "secondary_research": secondary_out,
            "study_context": study_ctx or {},
            "charts_spec": charts_spec,
            "tables": {
                "projection_24m_monthly": finance_out["projection_24m"]["monthly_m1_m12"],
                "projection_24m_quarterly": finance_out["projection_24m"]["quarterly_m13_m24"],
                "codebook": qual_out["codebook"],
            },
            "warnings": warnings,
            "chapter_slices": chapter_slices,
        }

        canonical_bytes = json.dumps(core_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        core_payload["sha256_hash"] = hashlib.sha256(canonical_bytes).hexdigest()

        if write_file:
            out_path = sim_dir / "analytics_bundle.json"
            out_path.write_text(json.dumps(core_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return core_payload

    @staticmethod
    def _build_echarts_specs(
        pricing: Dict[str, Any],
        funnel: Dict[str, Any],
        finance: Dict[str, Any],
        qual: Dict[str, Any],
        study_ctx: Optional[Dict[str, Any]] = None,
        cx: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        vw = pricing.get("van_westendorp") or {}
        gg = pricing.get("gabor_granger") or {}
        dofa_seed = (study_ctx or {}).get("dofa_seed") or {}
        nps_val = float(((cx or {}).get("nps") or {}).get("nps", 0.0))
        conv_pct = float(funnel.get("overall_awareness_to_adoption") or 0.25) * 100.0
        return {
            "van_westendorp": {
                "title": "Sensibilidad de Precios Van Westendorp (COP)",
                "prices": (vw.get("curves") or {}).get("prices", []),
                "series": vw.get("curves", {}),
                "markers": {"pmc": vw.get("pmc"), "opp": vw.get("opp"), "idp": vw.get("idp"), "pme": vw.get("pme")},
            },
            "gabor_granger": {
                "title": "Curva de Demanda e Ingreso Gabor-Granger (COP)",
                "points": gg.get("points", []),
                "optimal_price": gg.get("optimal_price"),
            },
            "funnel": {
                "title": "Embudo de Conversión 5 Etapas",
                "stages": funnel.get("funnel_stages", []),
            },
            "projection_24m": {
                "title": "Proyección Financiera 24 Meses (Escenario Base)",
                "monthly": finance["projection_24m"]["monthly_m1_m12"],
                "quarterly": finance["projection_24m"]["quarterly_m13_m24"],
            },
            "codebook_distribution": {
                "title": "Frecuencia de Objeciones y Drivers (100% del Corpus)",
                "items": [{"name": c["label"], "value": c["mentions"]} for c in qual.get("codebook", [])],
            },
            "dofa_matrix": {
                "title": "Matriz DOFA Cuantificada",
                "scores": {
                    "fortalezas": int(min(95, max(35, 55 + conv_pct * 0.6))),
                    "oportunidades": int(min(95, max(40, 62 + (15 if gg.get("optimal_price") else 0)))),
                    "debilidades": int(min(95, max(25, 50 - nps_val * 0.25))),
                    "amenazas": int(min(95, max(30, 58 - nps_val * 0.15))),
                },
                "items": {
                    "fortalezas": dofa_seed.get("fortalezas") or ["Propuesta de valor diferenciada"],
                    "oportunidades": dofa_seed.get("oportunidades") or ["Adopción digital en Colombia"],
                    "debilidades": dofa_seed.get("debilidades") or ["Fricción inicial de confianza"],
                    "amenazas": dofa_seed.get("amenazas") or ["Alternativas tradicionales sin costo"],
                },
            },
        }
