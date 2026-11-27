"""Muestreador demográfico estratificado y anti-complacencia para Colombia/LATAM."""

from __future__ import annotations

import hashlib
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from country_packs import get_country_pack
from country_packs.base_contracts import ArchetypeSpec, CityRecord, CountryPack, StratumItem

MBTI_POOL: List[str] = [
    "ENTJ", "ENFP", "INTP", "ESFP", "ESTP", "INFJ", "ENTP", "ISFP",
    "ESTJ", "ENFJ", "INTJ", "ISFJ", "ESFJ", "INFP", "ISTP", "ISTJ",
]

DYNAMIC_ROLES: List[str] = [
    "ConsumidorFinal",
    "CompradorFrecuente_Local",
    "DecisorB2B_Pyme",
    "Tendero_ComercianteBarrial",
    "CriticoDigital_Esceptico",
    "Regulador_Gremio_Opinion",
]

# Cuota mínima >= 40% en el polo escéptico/crítico para prevenir sycophancy (ESOMAR)
ATTITUDE_WEIGHTS: List[tuple[str, float]] = [
    ("esceptico", 0.25),
    ("critico_hate", 0.20),
    ("neutral", 0.28),
    ("promotor", 0.17),
    ("outlier", 0.10),
]

ATTITUDE_TO_STANCE: Dict[str, tuple[str, tuple[float, float]]] = {
    "promotor": ("supportive", (0.35, 0.85)),
    "neutral": ("neutral", (-0.15, 0.20)),
    "esceptico": ("opposing", (-0.65, -0.20)),
    "critico_hate": ("opposing", (-0.95, -0.45)),
    "outlier": ("observer", (-0.50, 0.50)),
}

CHANNELS_BY_STRATUM_TIER: Dict[int, List[str]] = {
    1: ["whatsapp_1on1", "street_survey", "facebook_groups", "radio"],
    2: ["whatsapp_1on1", "facebook_groups", "tiktok", "street_survey", "radio"],
    3: ["whatsapp_1on1", "instagram", "facebook_groups", "tiktok", "colombian_web"],
    4: ["whatsapp_1on1", "instagram", "colombian_web", "news_portals", "focus_group"],
    5: ["whatsapp_1on1", "colombian_web", "news_portals", "instagram", "focus_group"],
}

TRUST_BY_ATTITUDE: Dict[str, str] = {
    "promotor": "Media-Alta (valora soporte verificable y atención ágil)",
    "neutral": "Condicionada (pide pruebas, casos reales y precio claro)",
    "esceptico": "Baja (desconfía de promesas, verifica RUT, contrato y letra pequeña)",
    "critico_hate": "Muy Baja (asume posible estafa o trámite inútil hasta demostrar lo contrario)",
    "outlier": "Selectiva (solo confía en referido directo o gremio cercano)",
}


@dataclass
class DemographicAllocation:
    """Cuota sociodemográfica y conductual asignada a un agente sintético."""

    slot_index: int
    country_code: str
    country_name: str
    city_name: str
    divipola_code: str
    region_macro: str
    stratum_code: str
    wealth_tier_norm: int
    income_band_local: str
    static_archetype_code: str
    static_archetype_name: str
    controlled_slang: List[str] = field(default_factory=list)
    dynamic_study_role: str = "ConsumidorFinal"
    attitude_segment: str = "esceptico"
    stance: str = "opposing"
    sentiment_bias: float = -0.35
    activity_level: float = 0.55
    digital_trust_level: str = "Baja"
    preferred_channels: List[str] = field(default_factory=list)
    willingness_to_pay_band: str = "Medio"
    purchase_probability: float = 0.35
    mbti: str = "ENTP"
    age: int = 34
    gender: str = "male"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DemographicSampler:
    """Genera cuotas estratificadas sin sesgos chinos ni complacencia artificial."""

    def __init__(self, country_code: str = "co"):
        self.country_code = (country_code or "co").strip().lower()
        self.pack: CountryPack = get_country_pack(self.country_code)

    def sample_allocations(
        self,
        count: int,
        country_code: Optional[str] = None,
        target_cities: Optional[List[str]] = None,
        target_strata: Optional[List[str]] = None,
        entities: Optional[List[Any]] = None,
        seed: int = 42,
    ) -> List[DemographicAllocation]:
        """Construye exactamente `count` asignaciones estratificadas por ciudad, estrato y postura."""
        if count <= 0:
            return []

        pack = get_country_pack(country_code or self.country_code)
        rng = random.Random(seed)

        cities = self._resolve_cities(pack, target_cities)
        strata = self._resolve_strata(pack, target_strata)

        # Cuotas exactas por tamaño de muestra para garantizar >= 40% escépticos/críticos y <= 25% ISTJ
        attitudes = self._build_exact_attitude_pool(count, rng)
        city_slots = self._build_weighted_slots(
            items=cities,
            weights=[max(1, c.population_2026 or 100000) for c in cities],
            count=count,
            rng=rng,
        )
        stratum_slots = self._build_weighted_slots(
            items=strata,
            weights=[max(0.5, s.urban_weight_pct) for s in strata],
            count=count,
            rng=rng,
        )
        mbti_slots = self._build_mbti_pool(count, rng)
        activity_levels = self._build_varied_activities(count, rng)

        archetypes_by_region = self._index_archetypes(pack)
        default_archetype = pack.archetypes[0]

        allocations: List[DemographicAllocation] = []
        for idx in range(count):
            city = city_slots[idx]
            stratum = stratum_slots[idx]
            attitude = attitudes[idx]
            mbti = mbti_slots[idx]
            entity = entities[idx] if entities and idx < len(entities) else None

            arch = archetypes_by_region.get(city.cultural_archetype_default) or archetypes_by_region.get(
                city.region_macro.lower(), default_archetype
            )
            role = self._infer_dynamic_role(entity, idx, attitude)
            stance, bias_range = ATTITUDE_TO_STANCE[attitude]
            sentiment_bias = round(rng.uniform(*bias_range), 2)

            income_band = self._format_income_band(pack, stratum)
            wtp_band, purchase_prob = self._compute_wtp_and_prob(stratum, attitude, rng)
            channels = list(CHANNELS_BY_STRATUM_TIER.get(stratum.wealth_tier_norm, ["whatsapp_1on1"]))
            age = rng.randint(21, 62)
            gender = rng.choice(["male", "female"])

            allocations.append(
                DemographicAllocation(
                    slot_index=idx,
                    country_code=pack.country_code,
                    country_name=pack.country_name,
                    city_name=city.city_name,
                    divipola_code=city.divipola_code,
                    region_macro=city.region_macro,
                    stratum_code=stratum.code,
                    wealth_tier_norm=stratum.wealth_tier_norm,
                    income_band_local=income_band,
                    static_archetype_code=arch.code,
                    static_archetype_name=arch.name,
                    controlled_slang=list(arch.controlled_slang[:4]),
                    dynamic_study_role=role,
                    attitude_segment=attitude,
                    stance=stance,
                    sentiment_bias=sentiment_bias,
                    activity_level=activity_levels[idx],
                    digital_trust_level=TRUST_BY_ATTITUDE[attitude],
                    preferred_channels=channels,
                    willingness_to_pay_band=wtp_band,
                    purchase_probability=purchase_prob,
                    mbti=mbti,
                    age=age,
                    gender=gender,
                )
            )
        return allocations

    @staticmethod
    def _resolve_cities(pack: CountryPack, target_cities: Optional[List[str]]) -> List[CityRecord]:
        if target_cities:
            matched: List[CityRecord] = []
            for q in target_cities:
                c = pack.get_city_by_name_or_code(q)
                if c and c not in matched:
                    matched.append(c)
            if matched:
                return matched
        return pack.cities[:12]

    @staticmethod
    def _resolve_strata(pack: CountryPack, target_strata: Optional[List[str]]) -> List[StratumItem]:
        if target_strata:
            wanted = {str(s).strip().upper() for s in target_strata}
            matched = [
                s for s in pack.strata if s.code.upper() in wanted or s.code.upper().lstrip("E") in wanted
            ]
            if matched:
                return matched
        return pack.strata

    @staticmethod
    def _build_exact_attitude_pool(count: int, rng: random.Random) -> List[str]:
        pool: List[str] = []
        # Garantizar al menos 45% en polo escéptico/crítico para que incluso N pequeños superen >= 40%
        for label, weight in ATTITUDE_WEIGHTS:
            qty = max(1 if count >= 10 else 0, int(round(count * weight)))
            pool.extend([label] * qty)
        while len(pool) < count:
            pool.append("esceptico")
        if len(pool) > count:
            pool = pool[:count]

        skeptic_count = sum(1 for a in pool if a in ("esceptico", "critico_hate"))
        min_required = int((count * 0.42) + 0.999) if count >= 4 else 1
        i = 0
        while skeptic_count < min_required and i < len(pool):
            if pool[i] not in ("esceptico", "critico_hate"):
                pool[i] = "esceptico" if i % 2 == 0 else "critico_hate"
                skeptic_count += 1
            i += 1

        rng.shuffle(pool)
        return pool

    @staticmethod
    def _build_weighted_slots(items: List[Any], weights: List[float], count: int, rng: random.Random) -> List[Any]:
        if not items:
            return []
        if len(items) == 1:
            return [items[0]] * count
        chosen = rng.choices(items, weights=weights, k=count)
        # Asegurar cobertura mínima de los primeros elementos cuando count >= len(items)
        if count >= len(items):
            for idx, item in enumerate(items):
                chosen[idx] = item
            rng.shuffle(chosen)
        return chosen

    @staticmethod
    def _build_mbti_pool(count: int, rng: random.Random) -> List[str]:
        # Mantener ISTJ <= 12% (muy por debajo del tope 25%) usando rotación equitativa
        non_istj = [m for m in MBTI_POOL if m != "ISTJ"]
        pool: List[str] = []
        for idx in range(count):
            if idx % 12 == 11:
                pool.append("ISTJ")
            else:
                pool.append(non_istj[idx % len(non_istj)])
        rng.shuffle(pool)
        return pool

    @staticmethod
    def _build_varied_activities(count: int, rng: random.Random) -> List[float]:
        bands = [0.22, 0.38, 0.54, 0.68, 0.84, 0.92]
        values = [round(bands[i % len(bands)] + rng.uniform(-0.04, 0.04), 2) for i in range(count)]
        rng.shuffle(values)
        return [min(0.98, max(0.10, v)) for v in values]

    @staticmethod
    def _index_archetypes(pack: CountryPack) -> Dict[str, ArchetypeSpec]:
        idx: Dict[str, ArchetypeSpec] = {}
        for a in pack.archetypes:
            idx[a.code] = a
            idx[a.region_macro.lower()] = a
            for city in a.cities:
                idx[city.lower()] = a
        return idx

    @staticmethod
    def _infer_dynamic_role(entity: Optional[Any], idx: int, attitude: str) -> str:
        if entity is not None:
            etype = (getattr(entity, "get_entity_type", lambda: "")() or "").lower()
            ename = (getattr(entity, "name", "") or "").lower()
            if any(k in etype or k in ename for k in ("regulat", "superfinanc", "abog", "gremio", "fasecolda")):
                return "Regulador_Gremio_Opinion"
            if any(k in etype or k in ename for k in ("moto", "conduct", "taxi", "transp")):
                return "Conductor_Movilidad"
            if any(k in etype or k in ename for k in ("comerc", "tender", "taller", "pyme", "negoc", "empresa", "organization")):
                return "DecisorB2B_Pyme" if idx % 2 == 0 else "Tendero_ComercianteBarrial"
        if attitude == "critico_hate":
            return "CriticoDigital_Esceptico"
        return DYNAMIC_ROLES[idx % len(DYNAMIC_ROLES)]

    @staticmethod
    def _format_income_band(pack: CountryPack, stratum: StratumItem) -> str:
        low = int(round(stratum.income_smmlv_min * pack.min_wage_local))
        high = int(round(stratum.income_smmlv_max * pack.min_wage_local))
        return f"{pack.currency} {low:,} - {high:,} ({stratum.income_smmlv_min}-{stratum.income_smmlv_max} SMMLV)"

    @staticmethod
    def _compute_wtp_and_prob(stratum: StratumItem, attitude: str, rng: random.Random) -> tuple[str, float]:
        base_prob = {
            "promotor": 0.72,
            "neutral": 0.42,
            "esceptico": 0.22,
            "critico_hate": 0.08,
            "outlier": 0.30,
        }[attitude]
        tier_boost = (stratum.wealth_tier_norm - 3) * 0.04
        prob = round(min(0.95, max(0.03, base_prob + tier_boost + rng.uniform(-0.05, 0.05))), 2)
        wtp = {
            1: "Muy Sensible (< $40.000 COP / pago hito)",
            2: "Sensible ($40.000 - $70.000 COP con validación)",
            3: "Moderado ($70.000 - $150.000 COP si muestra valor)",
            4: "Medio-Alto ($150.000 - $400.000 COP / tarifa fija)",
            5: "Alto (> $400.000 COP priorizando ahorro de tiempo)",
        }[stratum.wealth_tier_norm]
        return wtp, prob

    @staticmethod
    def stable_seed_for_entities(project_id: str, entities: List[Any]) -> int:
        raw = f"{project_id}:{len(entities)}"
        return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8], 16)

    @staticmethod
    def summarize_profiles(profiles: List[Any]) -> Dict[str, Any]:
        """Genera resumen auditable de distribución por ciudad, estrato y postura."""
        cities: Dict[str, int] = {}
        strata: Dict[str, int] = {}
        attitudes: Dict[str, int] = {}
        istj_count = 0
        for p in profiles:
            city = getattr(p, "city_name", None) or (p.get("city_name") if isinstance(p, dict) else None) or "Sin especificar"
            stratum = getattr(p, "stratum_code", None) or (p.get("stratum_code") if isinstance(p, dict) else None) or "N/D"
            att = getattr(p, "attitude_segment", None) or (p.get("attitude_segment") if isinstance(p, dict) else None) or "neutral"
            mbti = getattr(p, "mbti", None) or (p.get("mbti") if isinstance(p, dict) else None) or ""
            cities[city] = cities.get(city, 0) + 1
            strata[stratum] = strata.get(stratum, 0) + 1
            attitudes[att] = attitudes.get(att, 0) + 1
            if str(mbti).upper() == "ISTJ":
                istj_count += 1
        total = max(1, len(profiles))
        skeptic_pct = round(100.0 * (attitudes.get("esceptico", 0) + attitudes.get("critico_hate", 0)) / total, 1)
        return {
            "total": len(profiles),
            "by_city": cities,
            "by_stratum": strata,
            "by_attitude": attitudes,
            "skeptic_critical_pct": skeptic_pct,
            "istj_pct": round(100.0 * istj_count / total, 1),
        }
