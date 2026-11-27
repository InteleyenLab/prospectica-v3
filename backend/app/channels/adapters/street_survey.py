"""Adaptador 3: Encuesta de calle presencial en puntos de interceptación colombianos."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, select_diverse_actors, sentiment_and_objection

INTERCEPT_POINTS = ["plaza_mercado", "centro_comercial", "paradero_transporte", "evento_feria"]


@ChannelRegistry.register
class StreetSurveyAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="street_survey",
        display_name="Encuesta de Calle (Interceptación territorial)",
        category="campo_presencial",
        topology=InteractionTopology.FIELD_INTERCEPT,
        supports_media_exposure=False,
        description="Interceptaciones presenciales en plazas, centros comerciales, paraderos y ferias con tasa real de rechazo.",
        peak_hours=[9, 10, 11, 12, 15, 16, 17],
    )

    def simulate_round(
        self,
        actors: List[Dict[str, Any]],
        study_context: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Dict[str, Any]:
        result = empty_result()
        topic = study_context.get("topic_short", "este servicio o producto")
        ladder = sorted(int(p) for p in (study_context.get("price_ladder_cop") or [35000, 50000, 70000, 100000, 140000]) if p)
        ref_price = float(ladder[len(ladder) // 2]) if ladder else 50000.0
        sample = select_diverse_actors(actors, limit=min(6, max(3, len(actors))), round_num=round_num)

        for idx, actor in enumerate(sample):
            af = actor_fields(actor)
            point = INTERCEPT_POINTS[(idx + round_num) % len(INTERCEPT_POINTS)]
            _, objection = sentiment_and_objection(af["attitude_segment"])

            if af["attitude_segment"] == "critico_hate" and idx % 3 == 0:
                status = "refused"
                text = f"[{point} - {af['city_name']}] No tengo tiempo para encuestas sobre {topic}, gracias."
            elif idx % 5 == 4:
                status = "time_pressure"
                text = f"[{point} - {af['city_name']}] Voy de afán pal trabajo: máximo pagaría COP {int(ref_price):,} por {topic} si es confiable."
            else:
                status = "completed"
                text = (
                    f"[{point} - {af['city_name']}, {af['stratum_code']}] Si explican sin enredos cómo funciona {topic} "
                    "y cumplen lo prometido, lo pensaría."
                )

            ts = now_iso()
            tier = int(actor.get("wealth_tier_norm") or 3)
            tier_mult = {1: 0.65, 2: 0.85, 3: 1.0, 4: 1.30, 5: 1.70}.get(tier, 1.0)
            base_price = ref_price * tier_mult
            gg_grid = {
                str(p): round(max(0.05, min(0.95, 0.80 - 0.55 * (i / max(1, len(ladder) - 1)))), 2)
                for i, p in enumerate(ladder)
            }

            result["survey_responses"].append(
                {
                    "respondent_id": f"street_{round_num}_{af['actor_agent_id']}",
                    "actor_agent_id": af["actor_agent_id"],
                    "channel_origin": "street_survey",
                    "status": status,
                    "city_divipola": af["city_divipola"],
                    "city_name": af["city_name"],
                    "region_macro": af["region_macro"],
                    "stratum_code": af["stratum_code"],
                    "wealth_tier_norm": tier,
                    "age": int(actor.get("age") or 34),
                    "gender": str(actor.get("gender") or "male"),
                    "dynamic_study_role": str(actor.get("dynamic_study_role") or "ConsumidorFinal"),
                    "attitude_segment": af["attitude_segment"],
                    "pain_score": 8 if af["attitude_segment"] != "promotor" else 6,
                    "trust_score": 3 if af["attitude_segment"] in ("esceptico", "critico_hate") else 7,
                    "nps_score": 3 if af["attitude_segment"] in ("esceptico", "critico_hate") else 8,
                    "csat_score": 2 if af["attitude_segment"] in ("esceptico", "critico_hate") else 4,
                    "ces_score": 4,
                    "vw_too_cheap": round(base_price * 0.35, 0),
                    "vw_cheap": round(base_price * 0.65, 0),
                    "vw_expensive": round(base_price * 1.15, 0),
                    "vw_too_expensive": round(base_price * 1.75, 0),
                    "nms_intent_cheap": 4 if af["attitude_segment"] == "promotor" else 3,
                    "nms_intent_expensive": 2 if af["attitude_segment"] in ("esceptico", "critico_hate") else 3,
                    "gg_grid_json": json.dumps(gg_grid),
                    "preferred_channel": point,
                    "main_objection": objection or "ninguna",
                    "verbatim_response": text,
                    "respondent_weight": 1.0,
                    "created_at": ts,
                }
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type=f"STREET_INTERCEPT_{status.upper()}",
                    content_text=text,
                    metadata={"intercept_point": point, "status": status},
                )
            )
        return result
