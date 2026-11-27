"""Adaptador 10: Televisión abierta nacional/regional y cable por franjas horarias."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, select_diverse_actors

TV_SLOTS = ["mañana", "noticiero_mediodia", "prime_noche"]


@ChannelRegistry.register
class TVAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="tv",
        display_name="Televisión (Nacional, regional y cable)",
        category="medios_masivos",
        topology=InteractionTopology.BROADCAST_MEDIA,
        supports_media_exposure=True,
        description="Exposición a menciones y pauta en TV por franjas y su impacto en legitimidad institucional.",
        peak_hours=[7, 12, 13, 19, 20, 21],
    )

    def simulate_round(
        self,
        actors: List[Dict[str, Any]],
        study_context: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Dict[str, Any]:
        result = empty_result()
        slot = TV_SLOTS[(round_num - 1) % len(TV_SLOTS)]
        sample = select_diverse_actors(actors, limit=min(5, max(2, len(actors))), round_num=round_num)
        ts = now_iso()
        for actor in sample:
            af = actor_fields(actor)
            is_critic = af["attitude_segment"] in ("esceptico", "critico_hate")
            msg = (
                f"[TV {slot} - {af['city_name']}] Salir en noticiero da algo más de respaldo, pero igual reviso opiniones reales."
                if is_critic
                else f"[TV {slot} - {af['city_name']}] Ver la nota en TV regional da confianza a familias que no manejan seguros."
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="TV_SEGMENT_REACTION",
                    content_text=msg,
                    metadata={"time_slot": slot},
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
                    "piece_format": "tv_spot_30s",
                    "time_slot": slot,
                    "recall_score": 0.76,
                    "comprehension_score": 0.72,
                    "credibility_score": 0.62 if is_critic else 0.86,
                    "prohibited_promise_rejected": False,
                    "reaction_text": msg,
                    "created_at": ts,
                }
            )
        return result
