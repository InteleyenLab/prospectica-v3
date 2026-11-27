"""Adaptador 5: TikTok Colombia (videos cortos, hook 3s y comentarios rápidos)."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, select_diverse_actors


@ChannelRegistry.register
class TikTokAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="tiktok",
        display_name="TikTok (Video corto y comentarios)",
        category="video_corto",
        topology=InteractionTopology.SHORT_VIDEO_FEED,
        supports_media_exposure=True,
        description="Evaluación de hooks de 3 segundos, ironía regional y comentarios en videos verticales.",
        peak_hours=[12, 18, 19, 20, 21, 22, 23],
    )

    def simulate_round(
        self,
        actors: List[Dict[str, Any]],
        study_context: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Dict[str, Any]:
        result = empty_result()
        topic = study_context.get("topic_short", "este producto o servicio")
        sample = select_diverse_actors(actors, limit=min(5, max(2, len(actors))), round_num=round_num)
        ts = now_iso()
        for actor in sample:
            af = actor_fields(actor)
            is_critic = af["attitude_segment"] in ("esceptico", "critico_hate")
            msg = (
                f"En {af['city_name']} vemos muchos videos promocionando servicios nuevos; ¿tienen respaldo real con {topic} "
                "o es puro gancho para pedir datos?"
                if is_critic
                else f"Buen dato ese resumen de cómo funciona {topic} en {af['city_name']}, guardado."
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="TIKTOK_COMMENT",
                    content_text=msg,
                    metadata={"video_script_card": f"Hook 3s: Conoce {topic}"},
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
                    "piece_format": "short_vertical_video_30s",
                    "time_slot": f"{simulated_hour:02d}:00",
                    "recall_score": 0.72,
                    "comprehension_score": 0.68,
                    "credibility_score": 0.35 if is_critic else 0.78,
                    "prohibited_promise_rejected": is_critic,
                    "reaction_text": msg,
                    "created_at": ts,
                }
            )
        return result
