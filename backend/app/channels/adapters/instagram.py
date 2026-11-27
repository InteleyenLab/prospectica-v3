"""Adaptador 6: Instagram Colombia (Reels, Stories interactivas y DMs)."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, select_diverse_actors


@ChannelRegistry.register
class InstagramAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="instagram",
        display_name="Instagram (Reels, Stories y DMs)",
        category="social_visual",
        topology=InteractionTopology.VISUAL_SOCIAL_FEED,
        supports_media_exposure=True,
        description="Interacción con pauta visual en feed, encuestas en Stories y mensajes directos.",
        peak_hours=[11, 12, 18, 19, 20, 21, 22],
    )

    def simulate_round(
        self,
        actors: List[Dict[str, Any]],
        study_context: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Dict[str, Any]:
        result = empty_result()
        sample = select_diverse_actors(actors, limit=min(5, max(2, len(actors))), round_num=round_num)
        ts = now_iso()
        for actor in sample:
            af = actor_fields(actor)
            is_critic = af["attitude_segment"] in ("esceptico", "critico_hate")
            msg = (
                f"Vi la pauta en Stories desde {af['city_name']}. Falta ver tarifas exactas en el perfil antes de escribir al DM."
                if is_critic
                else f"Me gustó el carrusel explicando documentos de RC en {af['city_name']}; escribí al DM por info."
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="IG_STORY_REPLY",
                    content_text=msg,
                    metadata={"surface": "stories_ad"},
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
                    "piece_format": "instagram_reel_carousel",
                    "time_slot": f"{simulated_hour:02d}:00",
                    "recall_score": 0.70,
                    "comprehension_score": 0.74,
                    "credibility_score": 0.42 if is_critic else 0.80,
                    "prohibited_promise_rejected": False,
                    "reaction_text": msg,
                    "created_at": ts,
                }
            )
        return result
