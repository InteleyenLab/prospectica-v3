"""Adaptador 7: Portales de noticias nacionales y regionales de Colombia."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, select_diverse_actors

PORTALS = ["El Tiempo / Portafolio", "El Colombiano", "El País Cali", "El Heraldo", "Vanguardia"]


@ChannelRegistry.register
class NewsPortalsAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="news_portals",
        display_name="Portales de Noticias (Nacionales y regionales)",
        category="prensa_digital",
        topology=InteractionTopology.EDITORIAL_COMMENTS,
        supports_media_exposure=True,
        description="Lectura de notas económicas y comentarios polarizados de lectores en prensa colombiana.",
        peak_hours=[7, 8, 12, 13, 20, 21],
    )

    def simulate_round(
        self,
        actors: List[Dict[str, Any]],
        study_context: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Dict[str, Any]:
        result = empty_result()
        topic = study_context.get("topic_short", "este modelo de servicio")
        sample = select_diverse_actors(actors, limit=min(5, max(2, len(actors))), round_num=round_num)
        ts = now_iso()
        for idx, actor in enumerate(sample):
            af = actor_fields(actor)
            portal = PORTALS[(idx + round_num) % len(PORTALS)]
            is_critic = af["attitude_segment"] in ("esceptico", "critico_hate")
            msg = (
                f"[{portal}] La SIC y las entidades competentes deberían vigilar el cumplimiento y transparencia de {topic} para proteger al consumidor."
                if is_critic
                else f"[{portal}] Buena alternativa en el mercado colombiano si {topic} brinda seguridad y reglas claras en {af['city_name']}."
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="NEWS_COMMENT",
                    content_text=msg,
                    metadata={"portal": portal},
                )
            )
            result["media_exposures"].append(
                {
                    "channel_id": self.config.channel_id,
                    "round_num": round_num,
                    "simulated_hour": simulated_hour,
                    "actor_agent_id": af["actor_agent_id"],
                    "actor_name": af["actor_name"],
                    "city_divipola": af["city_divipola"],
                    "stratum_code": af["stratum_code"],
                    "region_macro": af["region_macro"],
                    "piece_format": "editorial_article_comment",
                    "time_slot": portal,
                    "recall_score": 0.68,
                    "comprehension_score": 0.80,
                    "credibility_score": 0.55 if is_critic else 0.84,
                    "prohibited_promise_rejected": False,
                    "reaction_text": msg,
                    "created_at": ts,
                }
            )
        return result
