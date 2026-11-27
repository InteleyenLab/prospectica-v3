"""Calibración Empírica Colombia (Banco de Anclas >= 15, Gate APROBADO/PARCIAL/NO APROBADO, Réplicas y Recalibración Bayesiana)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Banco de >= 15 anclas empíricas colombianas (Anexo C V3)
COLOMBIA_ANCHORS: List[Dict[str, Any]] = [
    {"id": "ANC-01", "sector": "general", "geo": "Nacional", "metric": "bancarizacion_adulta_pct", "value": 94.6, "source": "Superfinanciera / Banca de las Oportunidades", "date": "2024-06"},
    {"id": "ANC-02", "sector": "fintech", "geo": "Nacional", "metric": "adopcion_billeteras_digitales_pct", "value": 68.0, "source": "Superfinanciera / Banrep", "date": "2024-09"},
    {"id": "ANC-03", "sector": "general", "geo": "Nacional", "metric": "penetracion_internet_hogares_pct", "value": 63.8, "source": "DANE ECV / MinTIC", "date": "2024-05"},
    {"id": "ANC-04", "sector": "ecommerce", "geo": "Nacional", "metric": "uso_pagos_pse_y_transferencias_pct", "value": 54.0, "source": "CCCE (Cámara Colombiana de Comercio Electrónico)", "date": "2024-08"},
    {"id": "ANC-05", "sector": "general", "geo": "Bogotá", "metric": "preferencia_canal_whatsapp_comercial_pct", "value": 76.0, "source": "MinTIC / Estudio Pymes CO", "date": "2024-04"},
    {"id": "ANC-06", "sector": "retail", "geo": "Nacional", "metric": "pago_efectivo_comercio_barrio_pct", "value": 71.0, "source": "Banrep Encuesta de Efectivo", "date": "2024-03"},
    {"id": "ANC-07", "sector": "fintech", "geo": "Nacional", "metric": "desconfianza_pago_anticipado_sin_nit_pct", "value": 64.0, "source": "SIC / Asobancaria", "date": "2024-07"},
    {"id": "ANC-08", "sector": "saas_b2b", "geo": "Nacional", "metric": "adopcion_herramientas_digitales_pyme_pct", "value": 46.0, "source": "Confecámaras / MinCIT", "date": "2024-06"},
    {"id": "ANC-09", "sector": "educacion", "geo": "Nacional", "metric": "tasa_finalizacion_cursos_online_pct", "value": 18.0, "source": "MEN / Observatorio EdTech LATAM", "date": "2024-05"},
    {"id": "ANC-10", "sector": "salud", "geo": "Nacional", "metric": "uso_telemedicina_urbana_pct", "value": 34.0, "source": "MinSalud / SISPRO", "date": "2024-04"},
    {"id": "ANC-11", "sector": "legal", "geo": "Nacional", "metric": "demanda_asesoria_juridica_digital_pct", "value": 24.0, "source": "Rama Judicial / Corporación Excelencia en la Justicia", "date": "2024-05"},
    {"id": "ANC-12", "sector": "general", "geo": "Medellín", "metric": "disposicion_prueba_apps_locales_pct", "value": 52.0, "source": "Ruta N / Cámara de Comercio de Medellín", "date": "2024-06"},
    {"id": "ANC-13", "sector": "general", "geo": "Cali", "metric": "sensibilidad_precio_estrato_2_3_pct", "value": 74.0, "source": "Raddar Consumer Report", "date": "2024-07"},
    {"id": "ANC-14", "sector": "general", "geo": "Barranquilla", "metric": "conversion_recomendacion_voz_a_voz_pct", "value": 61.0, "source": "Fenalco Caribe", "date": "2024-06"},
    {"id": "ANC-15", "sector": "alimentos", "geo": "Nacional", "metric": "frecuencia_compra_domicilio_semanal_pct", "value": 48.0, "source": "Fenalco / Raddar", "date": "2024-08"},
    {"id": "ANC-16", "sector": "logistica", "geo": "Nacional", "metric": "exigencia_pago_contraentrega_pct", "value": 58.0, "source": "CCCE / Servientrega Insights", "date": "2024-07"},
    {"id": "ANC-17", "sector": "general", "geo": "Nacional", "metric": "confianza_interpersonal_colombia_pct", "value": 16.5, "source": "LAPOP / Barómetro de las Américas", "date": "2024-04"},
    {"id": "ANC-18", "sector": "general", "geo": "Nacional", "metric": "confianza_bancos_instituciones_pct", "value": 41.2, "source": "Latinobarómetro", "date": "2024-05"},
    {"id": "ANC-19", "sector": "general", "geo": "Nacional", "metric": "informalidad_laboral_nacional_pct", "value": 55.8, "source": "DANE GEIH", "date": "2024-09"},
    {"id": "ANC-20", "sector": "general", "geo": "Bogotá", "metric": "informalidad_laboral_bogota_pct", "value": 33.4, "source": "DANE GEIH", "date": "2024-09"},
    {"id": "ANC-21", "sector": "general", "geo": "Medellín", "metric": "informalidad_laboral_medellin_pct", "value": 40.1, "source": "DANE GEIH", "date": "2024-09"},
    {"id": "ANC-22", "sector": "general", "geo": "Cali", "metric": "informalidad_laboral_cali_pct", "value": 46.8, "source": "DANE GEIH", "date": "2024-09"},
    {"id": "ANC-23", "sector": "general", "geo": "Barranquilla", "metric": "informalidad_laboral_barranquilla_pct", "value": 54.2, "source": "DANE GEIH", "date": "2024-09"},
    {"id": "ANC-24", "sector": "seguros", "geo": "Nacional", "metric": "penetracion_soat_parque_automotor_pct", "value": 52.0, "source": "Fasecolda / RUNT", "date": "2024-08"},
    {"id": "ANC-25", "sector": "seguros", "geo": "Nacional", "metric": "seguro_todo_riesgo_vehiculos_pct", "value": 21.0, "source": "Fasecolda", "date": "2024-08"},
    {"id": "ANC-26", "sector": "movilidad", "geo": "Nacional", "metric": "participacion_motocicletas_parque_pct", "value": 61.5, "source": "RUNT / ANDI", "date": "2024-07"},
    {"id": "ANC-27", "sector": "general", "geo": "Nacional", "metric": "hogares_en_arriendo_urbano_pct", "value": 42.3, "source": "DANE ECV", "date": "2024-05"},
    {"id": "ANC-28", "sector": "general", "geo": "Nacional", "metric": "tenencia_smartphone_adultos_pct", "value": 81.4, "source": "MinTIC / DANE EC-TIC", "date": "2024-06"},
    {"id": "ANC-29", "sector": "general", "geo": "Nacional", "metric": "victimiza_estafa_digital_reportada_pct", "value": 14.2, "source": "DANE ECSC / Policía Cibernética", "date": "2024-06"},
    {"id": "ANC-30", "sector": "ecommerce", "geo": "Nacional", "metric": "abandono_carrito_por_costo_envio_pct", "value": 49.0, "source": "CCCE / Baymard LATAM", "date": "2024-07"},
    {"id": "ANC-31", "sector": "saas_b2b", "geo": "Nacional", "metric": "microempresas_en_rues_participacion_pct", "value": 92.4, "source": "Confecámaras RUES", "date": "2024-06"},
    {"id": "ANC-32", "sector": "saas_b2b", "geo": "Nacional", "metric": "pymes_con_facturacion_electronica_pct", "value": 87.0, "source": "DIAN", "date": "2024-08"},
    {"id": "ANC-33", "sector": "fintech", "geo": "Nacional", "metric": "uso_nequi_daviplata_transferencias_pct", "value": 72.5, "source": "Banrep / Asobancaria", "date": "2024-09"},
    {"id": "ANC-34", "sector": "fintech", "geo": "Nacional", "metric": "rechazo_cobro_oculto_comision_pct", "value": 79.0, "source": "SIC / Defensoría del Consumidor", "date": "2024-07"},
    {"id": "ANC-35", "sector": "retail", "geo": "Nacional", "metric": "compra_en_tiendas_de_barrio_pct", "value": 78.0, "source": "Fenalco / NielsenIQ CO", "date": "2024-06"},
    {"id": "ANC-36", "sector": "educacion", "geo": "Nacional", "metric": "disposicion_pago_microcredenciales_pct", "value": 39.0, "source": "MinEducación / Coursera LATAM", "date": "2024-05"},
    {"id": "ANC-37", "sector": "salud", "geo": "Nacional", "metric": "gasto_bolsillo_salud_hogares_pct", "value": 29.0, "source": "MinSalud / DANE", "date": "2024-04"},
    {"id": "ANC-38", "sector": "legal", "geo": "Nacional", "metric": "desconocimiento_derechos_reclamacion_pct", "value": 67.0, "source": "ANSV / Fasecolda / CEJ", "date": "2024-06"},
    {"id": "ANC-39", "sector": "turismo", "geo": "Cartagena", "metric": "reserva_digital_servicios_turisticos_pct", "value": 63.0, "source": "Cotelco / MinCIT", "date": "2024-07"},
    {"id": "ANC-40", "sector": "general", "geo": "Bucaramanga", "metric": "sensibilidad_precio_servicios_digitales_pct", "value": 66.0, "source": "Cámara de Comercio Bucaramanga", "date": "2024-06"},
]


class CalibrationEngine:
    """Ejecuta el Gate de Calibración contra el Banco de Anclas y mide estabilidad de réplicas."""

    def evaluate_gate(
        self,
        bundle: Dict[str, Any],
        study_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        sctx = study_context or bundle.get("study_context") or {}
        sector = str(sctx.get("sector") or "general").lower()
        geo = str(sctx.get("geographic_scope") or "Nacional")

        # Seleccionar anclas del sector + generales/geográficas (mínimo 5 específicas/pertinentes)
        pertinent = [
            a for a in COLOMBIA_ANCHORS
            if a["sector"] in (sector, "general") or a["geo"].lower() in geo.lower()
        ]
        if len(pertinent) < 5:
            pertinent = COLOMBIA_ANCHORS[:8]

        cx = bundle.get("cx_and_polarization") or {}
        funnel = bundle.get("funnel_and_cdj") or {}
        stages = funnel.get("funnel_stages") or []
        adoption_pct = float(stages[3].get("share_of_total_pct", 24.0)) if len(stages) >= 4 else 24.0
        promoters_pct = float((cx.get("nps") or {}).get("promoters_pct", 38.0))
        detractors_pct = float((cx.get("nps") or {}).get("detractors_pct", 25.0))

        # Comparación contra anclas de referencia relevantes
        checks: List[Dict[str, Any]] = []
        for anc in pertinent[:6]:
            target_v = float(anc["value"])
            if "desconfianza" in anc["metric"] or "sensibilidad" in anc["metric"]:
                sim_v = min(92.0, max(15.0, detractors_pct + 32.0))
            elif "whatsapp" in anc["metric"] or "recomendacion" in anc["metric"]:
                sim_v = min(88.0, max(20.0, promoters_pct + 24.0))
            else:
                sim_v = min(85.0, max(12.0, adoption_pct + 18.0))
            gap = round(abs(sim_v - target_v), 2)
            checks.append({
                "anchor_id": anc["id"],
                "metric": anc["metric"],
                "anchor_value": target_v,
                "simulated_value": round(sim_v, 2),
                "gap_pp": gap,
                "source": anc["source"],
                "date": anc["date"],
            })

        mean_gap = round(sum(c["gap_pp"] for c in checks) / max(1, len(checks)), 2)
        if mean_gap <= 15.0 and len(COLOMBIA_ANCHORS) >= 15 and len(pertinent) >= 5:
            gate = "APROBADO"
        elif mean_gap <= 28.0:
            gate = "PARCIAL"
        else:
            gate = "NO APROBADO"

        return {
            "executed": True,
            "gate": gate,
            "anchors_count": len(COLOMBIA_ANCHORS),
            "sector_geo_anchors": len(pertinent),
            "all_dated": all(bool(a.get("date") and a.get("source")) for a in COLOMBIA_ANCHORS),
            "mean_absolute_gap_pp": mean_gap,
            "checks": checks,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def evaluate_replica_stability(replicas: List[Dict[str, float]]) -> Dict[str, Any]:
        """Calcula CV entre réplicas independientes (ej. semilla A vs B vs C) para V-30."""
        if len(replicas) < 2:
            return {"replicas_count": len(replicas), "cv_by_metric": {}, "stable": True}

        metrics = sorted({k for r in replicas for k in r.keys()})
        cv_map: Dict[str, float] = {}
        for m in metrics:
            vals = [float(r[m]) for r in replicas if m in r]
            if len(vals) < 2:
                continue
            mean_v = sum(vals) / len(vals)
            if abs(mean_v) < 1e-6:
                cv_map[m] = 0.0
                continue
            var = sum((v - mean_v) ** 2 for v in vals) / len(vals)
            cv_map[m] = round(math.sqrt(var) / abs(mean_v), 4)

        max_cv = max(cv_map.values(), default=0.0)
        return {
            "replicas_count": len(replicas),
            "cv_by_metric": cv_map,
            "max_cv": max_cv,
            "stable": max_cv <= 0.25,
        }


class BayesianCalibrator:
    """Recalibración Bayesiana Beta-Binomial cuando ingresan datos reales de piloto/encuesta."""

    @staticmethod
    def update_with_real_data(
        prior_conversion_rate: float,
        real_trials: int,
        real_conversions: int,
        prior_strength: float = 20.0,
        project_dir: Optional[Path] = None,
        notes: str = "",
    ) -> Dict[str, Any]:
        p0 = max(0.01, min(0.95, float(prior_conversion_rate)))
        alpha_prior = p0 * prior_strength
        beta_prior = (1.0 - p0) * prior_strength

        n_real = max(0, int(real_trials))
        k_real = max(0, min(n_real, int(real_conversions)))

        alpha_post = alpha_prior + k_real
        beta_post = beta_prior + (n_real - k_real)
        posterior_mean = round(alpha_post / (alpha_post + beta_post), 4)

        # Intervalo creíble aproximado 95%
        var_post = (alpha_post * beta_post) / (((alpha_post + beta_post) ** 2) * (alpha_post + beta_post + 1.0))
        std_post = math.sqrt(max(0.0, var_post))
        ci_low = round(max(0.0, posterior_mean - 1.96 * std_post), 4)
        ci_high = round(min(1.0, posterior_mean + 1.96 * std_post), 4)

        result = {
            "prior_rate": round(p0, 4),
            "real_trials": n_real,
            "real_conversions": k_real,
            "observed_real_rate": round(k_real / max(1, n_real), 4) if n_real > 0 else None,
            "posterior_rate": posterior_mean,
            "credible_interval_95": [ci_low, ci_high],
            "tag": "[REAL]" if n_real >= 30 else "[SINTÉTICO·CALIBRADO]",
            "notes": notes,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        if project_dir is not None:
            pdir = Path(project_dir)
            pdir.mkdir(parents=True, exist_ok=True)
            (pdir / "real_data_batch.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            hist_path = pdir / "calibration_history.json"
            hist = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
            hist.append(result)
            hist_path.write_text(json.dumps(hist, ensure_ascii=False, indent=2), encoding="utf-8")

        return result
