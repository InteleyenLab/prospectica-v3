"""Adaptador legado OASIS encapsulando `legacy_twitter` y `legacy_reddit`."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, select_diverse_actors


@ChannelRegistry.register
class LegacyTwitterAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="legacy_twitter",
        display_name="Plaza Pública Digital (Debate Comunitario)",
        category="comunidad_digital",
        topology=InteractionTopology.MICROBLOG_LEGACY,
        is_legacy=True,
        default_enabled=False,
        description="Publicaciones breves y debate público abierto entre usuarios.",
        peak_hours=[9, 12, 19, 20, 21],
    )

    def simulate_round(
        self,
        actors: List[Dict[str, Any]],
        study_context: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Dict[str, Any]:
        result = empty_result()
        topic = study_context.get("topic_short", "esta propuesta")
        sample = select_diverse_actors(actors, limit=min(4, max(2, len(actors))), round_num=round_num)
        for actor in sample:
            af = actor_fields(actor)
            msg = (
                f"[{af['city_name']}] Debate abierto sobre {topic}: "
                "el mercado exige transparencia total en costos, tiempos y garantías."
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="CREATE_POST",
                    content_text=msg,
                )
            )
        return result


@ChannelRegistry.register
class LegacyRedditAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="legacy_reddit",
        display_name="Comunidad Temática de Discusión",
        category="comunidad_digital",
        topology=InteractionTopology.MICROBLOG_LEGACY,
        is_legacy=True,
        default_enabled=False,
        description="Hilos largos de análisis y debate temático entre usuarios.",
        peak_hours=[18, 19, 20, 21, 22],
    )

    def simulate_round(
        self,
        actors: List[Dict[str, Any]],
        study_context: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Dict[str, Any]:
        result = empty_result()
        topic = study_context.get("topic_short", "este servicio")
        sample = select_diverse_actors(actors, limit=min(4, max(2, len(actors))), round_num=round_num)
        for actor in sample:
            af = actor_fields(actor)
            msg = (
                f"Hilo de análisis ({af['city_name']}, {af['stratum_code']}): evaluar si el valor y la propuesta de {topic} "
                "resuelven realmente la fricción frente a las alternativas actuales."
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="CREATE_COMMENT",
                    content_text=msg,
                )
            )
        return result
