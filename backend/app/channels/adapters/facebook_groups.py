"""Adaptador 4: Grupos de Facebook barriales, moteros y de comerciantes en Colombia."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, regional_greeting, select_diverse_actors


@ChannelRegistry.register
class FacebookGroupsAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="facebook_groups",
        display_name="Grupos de Facebook (Comunidades y gremios)",
        category="social_comunidad",
        topology=InteractionTopology.COMMUNITY_BOARD,
        supports_media_exposure=False,
        description="Discusiones vecinales, clubes de motos y comerciantes donde se validan referencias y alertas de estafa.",
        peak_hours=[12, 13, 19, 20, 21, 22],
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
        sample = select_diverse_actors(actors, limit=min(5, max(2, len(actors))), round_num=round_num)
        for actor in sample:
            af = actor_fields(actor)
            greet = regional_greeting(af["region_macro"])
            if af["attitude_segment"] in ("esceptico", "critico_hate"):
                msg = (
                    f"{greet} ojo en el grupo de {af['city_name']}: ¿alguien ya ha probado {topic}? "
                    "A veces cobran tarifas o comisiones que no justifican el beneficio frente a hacerlo directo."
                )
            else:
                msg = (
                    f"{greet} en mi comunidad de {af['city_name']} están comentando sobre {topic}; "
                    "si cumple con transparencia en precios y respaldo verificable, sí resuelve un problema real."
                )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="FB_GROUP_COMMENT",
                    content_text=msg,
                    metadata={"group_scope": f"Comunidad_{af['city_name']}"},
                )
            )
        return result
