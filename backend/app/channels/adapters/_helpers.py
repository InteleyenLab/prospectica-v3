"""Utilidades compartidas para los adaptadores multicanal colombianos/LATAM."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..base import ChannelEvent

OBJECTION_BY_ATTITUDE: Dict[str, Optional[str]] = {
    "esceptico": "desconfianza_pago_anticipado",
    "critico_hate": "temor_estafa_o_tramite_inutil",
    "outlier": "prefiere_alternativa_tradicional",
    "neutral": None,
    "promotor": None,
}

REGIONAL_PREFIX: Dict[str, List[str]] = {
    "Andina": ["En mi caso en la ciudad,", "Siendo sincero desde acá,", "Por lo que veo día a día,"],
    "Andina Centro": ["Qué pena preguntar directo:", "Mirando bien las cuentas,", "A nivel práctico le digo:"],
    "Antioquia": ["Vea pues, haciendo números,", "Desde mi experiencia acá,", "Si da tranquilidad y orden,"],
    "Paisa / Eje Cafetero": ["Vea pues, haciendo números,", "Desde mi experiencia acá,", "Si da tranquilidad y orden,"],
    "Pacífica": ["Vea, mirando cómo funciona,", "Acá en el barrio pensamos que", "Si ahorra vueltas y tiempo,"],
    "Caribe": ["Oye, te soy franco:", "Acá primero preguntamos si", "La verdad es que por acá"],
    "Santanderes": ["Yendo al grano le digo:", "Si cumplen lo que prometen,", "Aquí uno revisa primero"],
    "Andina Sur": ["Venga le digo con sinceridad:", "Mirando el gasto mensual,", "Para decidir bien necesito"],
    "Orinoquía": ["Por acá valoramos que", "Cuando la señal falla toca", "Si funciona sin tanta vuelta,"],
    "Amazonía": ["En esta zona todo cuesta más,", "Lo clave acá es que", "Si no exige trámites largos,"],
}

CHANNEL_FRICTION_RATE: Dict[str, float] = {
    "whatsapp_1on1": 0.34,
    "focus_group": 0.44,
    "street_survey": 0.52,
    "facebook_groups": 0.58,
    "tiktok": 0.27,
    "instagram": 0.31,
    "news_portals": 0.41,
    "colombian_web": 0.38,
    "advertising": 0.24,
    "tv": 0.18,
    "radio": 0.22,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def actor_fields(actor: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "actor_agent_id": int(actor.get("user_id", actor.get("agent_id", 0))),
        "actor_name": str(actor.get("name") or actor.get("username") or "Ciudadano"),
        "city_divipola": str(actor.get("divipola_code") or "11001"),
        "city_name": str(actor.get("city_name") or "Bogotá D.C."),
        "stratum_code": str(actor.get("stratum_code") or "E3"),
        "region_macro": str(actor.get("region_macro") or "Andina Centro"),
        "attitude_segment": str(actor.get("attitude_segment") or "esceptico"),
    }


def regional_greeting(region_macro: str, slot_index: int = 0) -> str:
    pool = REGIONAL_PREFIX.get(region_macro) or [
        "En mi experiencia,",
        "Revisando el costo-beneficio,",
        "Desde mi punto de vista,",
        "Siendo realista con el bolsillo,",
        "Antes de comprometerme,",
    ]
    return pool[slot_index % len(pool)]


def sentiment_and_objection(attitude: str) -> Tuple[float, Optional[str]]:
    if attitude == "promotor":
        return 0.65, None
    if attitude == "neutral":
        return 0.05, None
    if attitude == "esceptico":
        return -0.45, "desconfianza_pago_anticipado"
    if attitude == "critico_hate":
        return -0.80, "temor_estafa_o_tramite_inutil"
    return -0.25, "prefiere_alternativa_tradicional"


def build_event(
    actor: Dict[str, Any],
    channel_id: str,
    round_num: int,
    simulated_hour: int,
    action_type: str,
    content_text: str,
    sentiment_override: Optional[float] = None,
    objection_override: Optional[str] = None,
    is_friction_override: Optional[bool] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> ChannelEvent:
    af = actor_fields(actor)
    default_sent, default_obj = sentiment_and_objection(af["attitude_segment"])
    final_sent = default_sent if sentiment_override is None else sentiment_override
    final_obj = objection_override if objection_override is not None else default_obj
    if af["attitude_segment"] == "neutral" and final_obj is None:
        low_txt = (content_text or "").lower()
        if final_sent <= -0.20 or any(w in low_txt for w in ("caro", "duda", "estafa", "desconf", "no veo garant")):
            final_obj = "duda_relacion_precio_beneficio"
    if is_friction_override is not None:
        final_friction = is_friction_override
    else:
        base_fr = CHANNEL_FRICTION_RATE.get(channel_id, 0.36)
        att_boost = 0.22 if af["attitude_segment"] in ("esceptico", "critico_hate") else (-0.15 if af["attitude_segment"] == "promotor" else 0.0)
        eff_prob = max(0.08, min(0.92, base_fr + att_boost))
        bucket = ((af["actor_agent_id"] * 37 + round_num * 13 + len(channel_id) * 7) % 100) / 100.0
        final_friction = bucket < eff_prob
    return ChannelEvent(
        actor_agent_id=af["actor_agent_id"],
        actor_name=af["actor_name"],
        city_divipola=af["city_divipola"],
        city_name=af["city_name"],
        stratum_code=af["stratum_code"],
        region_macro=af["region_macro"],
        attitude_segment=af["attitude_segment"],
        channel_id=channel_id,
        round_num=round_num,
        simulated_hour=simulated_hour,
        action_type=action_type,
        content_text=content_text,
        sentiment_score=final_sent,
        objection_tag=final_obj,
        is_friction=final_friction,
        metadata=metadata or {},
    )


def select_diverse_actors(actors: List[Dict[str, Any]], limit: int, round_num: int) -> List[Dict[str, Any]]:
    """Selecciona un subconjunto diverso equilibrando regiones y posturas (promotor, neutral, escéptico, crítico)."""
    if not actors:
        return []
    if len(actors) <= limit:
        return list(actors)
    by_attitude: Dict[str, List[Dict[str, Any]]] = {}
    for actor in actors:
        att = str(actor.get("attitude_segment") or "neutral")
        by_attitude.setdefault(att, []).append(actor)

    chosen: List[Dict[str, Any]] = []
    attitudes = ["promotor", "neutral", "esceptico", "critico_hate", "outlier"]
    extra_atts = [k for k in by_attitude.keys() if k not in attitudes]
    ordered_atts = [k for k in attitudes + extra_atts if by_attitude.get(k)]
    cursor = round_num
    while len(chosen) < limit and ordered_atts:
        for att in list(ordered_atts):
            bucket = by_attitude[att]
            if not bucket:
                ordered_atts.remove(att)
                continue
            pick = bucket.pop(cursor % len(bucket))
            chosen.append(pick)
            if len(chosen) >= limit:
                break
        cursor += 1
    return chosen


def empty_result() -> Dict[str, Any]:
    return {
        "events": [],
        "whatsapp_sessions": [],
        "focus_group_turns": [],
        "survey_responses": [],
        "media_exposures": [],
    }
