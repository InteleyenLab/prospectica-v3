"""Adaptador 11: Radio AM/FM local y programas de opinión regional."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, select_diverse_actors


@ChannelRegistry.register
class RadioAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="radio",
        display_name="Radio (Emisoras locales AM/FM y opinión)",
        category="medios_masivos",
        topology=InteractionTopology.BROADCAST_MEDIA,
        supports_media_exposure=True,
        description="Cuñas radiales y menciones en tráfico matutino para conductores, tenderos y ciudades intermedias.",
        peak_hours=[6, 7, 8, 12, 17, 18],
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
                f"[Radio local {af['city_name']}] Escuché la cuña en el trancón: si dan un WhatsApp corto y no piden plata "
                "sin revisar primero el caso, la gente de calle sí llama."
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="RADIO_LISTENER_REACTION",
                    content_text=msg,
                    metadata={"band": "FM_AM_Regional"},
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
                    "piece_format": "radio_cuna_20s",
                    "time_slot": f"{simulated_hour:02d}:00_trafico",
                    "recall_score": 0.74,
                    "comprehension_score": 0.75,
                    "credibility_score": 0.58 if is_critic else 0.81,
                    "prohibited_promise_rejected": False,
                    "reaction_text": msg,
                    "created_at": ts,
                }
            )
        return result
