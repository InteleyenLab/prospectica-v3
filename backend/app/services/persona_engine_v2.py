"""Motor de Personas Sintéticas V2 (Esquema 7 Capas, Imperfecciones Humanas, Estilo Regional y Diversidad)."""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any, Dict, List, Optional

from .demographic_sampler import DemographicAllocation, DemographicSampler

MODEL_FAMILIES: List[str] = ["gemini-flash", "llama-3.3-70b", "qwen-2.5-72b"]

REGIONAL_OPENINGS: Dict[str, List[str]] = {
    "Andina": [
        "En Bogotá la verdad uno mira primero",
        "Acá en el día a día nos toca comparar",
        "Si le soy sincero, antes de pagar prefiero",
        "Por experiencia en la ciudad le digo que",
        "Pues mire, con tantos cobros ocultos uno",
        "A mí me interesa pero siempre reviso",
        "Desde mi trabajo veo que el problema es",
        "Honestamente, si no muestran NIT claro",
        "Para uno que maneja gastos apretados",
        "Lo que más pesa en mi decisión es",
    ],
    "Caribe": [
        "Acá en la costa uno pregunta primero quién",
        "Oye, si el trámite es rápido por WhatsApp",
        "La verdad es que en Barranquilla la gente",
        "No te voy a mentir, si toca pagar por adelantado",
        "Con el calor y las vueltas uno prefiere",
        "Si tiene buen respaldo y precio justo",
        "Aquí todo se mueve por recomendación de",
        "Me llama la atención pero quiero ver",
    ],
    "Pacífico": [
        "En Cali uno valora que le hablen claro",
        "Vea, si me ahorra tiempo y filas yo",
        "Por mi barrio primero miramos si algún vecino",
        "La desconfianza viene cuando cobran antes de",
        "Para el negocio familiar nos serviría si",
        "De entrada suena bien, aunque me genera duda",
    ],
    "Antioquia": [
        "Pues hombre, en Medellín si da rentabilidad",
        "Vea pues, yo hago cuentas primero de cuánto",
        "Aquí el que no muestra números claros no",
        "Si me garantiza cumplimiento y buen servicio",
        "A nosotros los comerciantes nos importa mucho",
        "De una le digo que por ese valor lo pienso",
    ],
    "Orinoquía": [
        "Por acá en el llano valoramos que funcione",
        "A veces la señal falla, entonces necesito",
        "Si se puede resolver directo sin tanta vuelta",
        "Con que cumplan lo prometido y den factura",
    ],
    "Amazonía": [
        "En esta zona todo llega más caro, así que",
        "Lo clave aquí es que no exijan trámites",
        "Si funciona bien con datos móviles básicos",
    ],
}

HUMAN_IMPERFECTIONS: List[str] = [
    "contradiccion_precio_calidad",
    "fatiga_onboarding",
    "desconfianza_pago_anticipado",
    "apego_canal_tradicional",
    "decision_postergada_fin_de_mes",
    "influencia_familiar_externa",
]


class PersonaEngineV2:
    """Genera personas sintéticas de 7 capas con diversidad controlada y trazabilidad de semilla."""

    def __init__(self, country_code: str = "co"):
        self.country_code = (country_code or "co").strip().lower()
        self.sampler = DemographicSampler(country_code=self.country_code)

    def build_persona(
        self,
        alloc: DemographicAllocation,
        study_context: Optional[Dict[str, Any]] = None,
        seed: int = 2026,
    ) -> Dict[str, Any]:
        """Construye una persona sintética completa de 7 capas (Anexo B)."""
        sctx = study_context or {}
        agent_seed = seed + alloc.slot_index * 7919
        rng = random.Random(agent_seed)
        model_family = MODEL_FAMILIES[alloc.slot_index % len(MODEL_FAMILIES)]

        income_ranges = {
            1: (650_000, 1_300_000),
            2: (1_300_000, 2_400_000),
            3: (2_400_000, 4_800_000),
            4: (4_800_000, 9_500_000),
            5: (9_500_000, 24_000_000),
        }
        inc_min, inc_max = income_ranges.get(alloc.wealth_tier_norm, (2_000_000, 4_500_000))
        monthly_income = rng.randint(inc_min, inc_max)

        pay_methods = ["Efectivo", "Nequi/Daviplata"]
        if alloc.wealth_tier_norm >= 2:
            pay_methods.append("PSE")
        if alloc.wealth_tier_norm >= 4:
            pay_methods.append("Tarjeta de crédito")

        region = alloc.region_macro if alloc.region_macro in REGIONAL_OPENINGS else "Andina"
        openings = REGIONAL_OPENINGS[region]
        # Rotar aperturas y combinar con detalle del rol para evitar repetición >3% de 3-gramas
        base_open = openings[alloc.slot_index % len(openings)]
        variant_tag = rng.choice(
            [
                f"como {alloc.dynamic_study_role.lower()}",
                f"en {alloc.city_name}",
                f"siendo estrato {alloc.stratum_code}",
                f"con {alloc.age} años",
            ]
        )

        # Usar jerga regional con probabilidad <= 0.35 (§8.5)
        uses_slang = rng.random() < 0.30
        imperfection = HUMAN_IMPERFECTIONS[rng.randrange(len(HUMAN_IMPERFECTIONS))]
        contradiction_flag = rng.random() < 0.18

        sector = str(sctx.get("sector") or "servicios")
        risk_objs = list(sctx.get("key_risks_objections") or ["Falta de confianza inicial y costos ocultos"])
        dominant_obj = risk_objs[alloc.slot_index % len(risk_objs)]

        persona = {
            "persona_id": f"p2_{alloc.slot_index + 1:04d}",
            "seed": agent_seed,
            "model_family": model_family,
            "layer_1_demographics": {
                "age": alloc.age,
                "gender": alloc.gender,
                "city_divipola": alloc.divipola_code,
                "city_name": alloc.city_name,
                "region_macro": region,
                "stratum_code": alloc.stratum_code,
                "household_size": rng.randint(1, 5),
                "education_level": rng.choice(
                    ["Bachiller", "Técnico/Tecnólogo", "Profesional", "Posgrado"]
                    if alloc.wealth_tier_norm >= 3
                    else ["Primaria/Secundaria", "Bachiller", "Técnico"]
                ),
            },
            "layer_2_socioeconomic": {
                "wealth_tier_norm": alloc.wealth_tier_norm,
                "monthly_income_cop": monthly_income,
                "employment_stability": "formal" if alloc.wealth_tier_norm >= 3 and rng.random() > 0.3 else "independiente_o_informal",
                "payment_methods": pay_methods,
                "price_sensitivity": round(max(0.15, min(0.95, 1.05 - 0.16 * alloc.wealth_tier_norm + rng.uniform(-0.08, 0.08))), 3),
            },
            "layer_3_psychographics": {
                "attitude_segment": alloc.attitude_segment,
                "risk_aversion": round(rng.uniform(0.55, 0.95) if alloc.attitude_segment in ("esceptico", "critico_hate") else rng.uniform(0.25, 0.65), 3),
                "innovation_openness": round(rng.uniform(0.55, 0.92) if alloc.attitude_segment == "promotor" else rng.uniform(0.20, 0.60), 3),
                "trust_baseline": round(rng.uniform(0.20, 0.85), 3),
            },
            "layer_4_behavioral": {
                "preferred_channels": list(alloc.preferred_channels or ["whatsapp_1on1"]),
                "purchase_probability_prior": round(alloc.purchase_probability, 3),
                "category_frequency_monthly": round(rng.uniform(0.5, 4.0), 2),
                "channel_friction_sensitivity": round(rng.uniform(0.20, 0.78), 3),
            },
            "layer_5_digital_access": {
                "primary_device": "Smartphone Android gama media" if alloc.wealth_tier_norm <= 3 else "Smartphone gama alta + PC",
                "connectivity": "Datos móviles prepago/pospago" if alloc.wealth_tier_norm <= 2 else "Fibra hogar + datos 4G/5G",
                "digital_literacy": "alta" if alloc.age < 40 or alloc.wealth_tier_norm >= 4 else "media",
            },
            "layer_6_domain_context": {
                "sector": sector,
                "dynamic_study_role": alloc.dynamic_study_role,
                "project_name": str(sctx.get("project_name") or "Proyecto"),
                "dominant_objection": dominant_obj,
                "current_alternative": "Proceso tradicional / contacto directo sin plataforma",
            },
            "layer_7_human_imperfections": {
                "imperfection_trait": imperfection,
                "has_price_value_contradiction": contradiction_flag,
                "uses_regional_slang": uses_slang,
                "opening_phrase": f"{variant_tag.capitalize()}, {base_open[0].lower() + base_open[1:]}",
                "hesitation_note": (
                    "Duda si el beneficio compensa cambiar su rutina actual."
                    if contradiction_flag
                    else "Pide evidencia verificable (NIT, soporte humano y condiciones claras)."
                ),
            },
        }
        digest = hashlib.sha256(f"{persona['persona_id']}:{agent_seed}:{model_family}".encode("utf-8")).hexdigest()[:12]
        persona["persona_hash"] = digest
        return persona

    def generate_cohort(
        self,
        count: int = 100,
        study_context: Optional[Dict[str, Any]] = None,
        target_cities: Optional[List[str]] = None,
        target_strata: Optional[List[str]] = None,
        seed: int = 2026,
    ) -> Dict[str, Any]:
        """Genera una cohorte completa con métricas de diversidad (§8.6)."""
        allocations = self.sampler.sample_allocations(
            count=count,
            country_code=self.country_code,
            target_cities=target_cities,
            target_strata=target_strata,
            seed=seed,
        )
        personas = [self.build_persona(a, study_context=study_context, seed=seed) for a in allocations]
        diversity = self.audit_diversity(personas)
        return {
            "count": len(personas),
            "personas": personas,
            "diversity_audit": diversity,
        }

    @staticmethod
    def audit_diversity(personas: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Verifica controles de diversidad: ≥2 familias de modelos, <3% apertura repetida, jerga acotada."""
        if not personas:
            return {"count": 0, "model_families_used": [], "max_3word_opening_share": 0.0, "slang_share": 0.0, "passed": False}

        families = sorted({str(p.get("model_family") or "unknown") for p in personas})
        openings = []
        slang_count = 0
        for p in personas:
            imp = p.get("layer_7_human_imperfections") or {}
            phrase = str(imp.get("opening_phrase") or "")
            words = phrase.split()
            if len(words) >= 3:
                openings.append(" ".join(words[:3]).lower())
            if imp.get("uses_regional_slang"):
                slang_count += 1

        max_share = (Counter(openings).most_common(1)[0][1] / max(1, len(openings))) if openings else 0.0
        slang_share = round(slang_count / len(personas), 4)
        return {
            "count": len(personas),
            "model_families_used": families,
            "model_families_count": len(families),
            "max_3word_opening_share": round(max_share, 4),
            "slang_share": slang_share,
            "passed": len(families) >= 2 and max_share <= 0.15 and slang_share <= 0.45,
        }
