"""Adaptador 2: Mesa de Focus Group moderada multi-región y multi-estrato."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, regional_greeting, select_diverse_actors, sentiment_and_objection


BLOCKS = [
    "bloque_1_dolor_y_necesidad",
    "bloque_2_confianza_y_propuesta",
    "bloque_3_sensibilidad_precio",
    "bloque_4_canales_y_cierre",
]


@ChannelRegistry.register
class FocusGroupAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="focus_group",
        display_name="Focus Group (Mesa moderada heterogénea)",
        category="cualitativo",
        topology=InteractionTopology.MODERATED_GROUP,
        supports_media_exposure=False,
        description="Mesas de 6 a 10 arquetipos con contagio social, contraste regional y registro de objeciones.",
        peak_hours=[18, 19, 20],
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
        block_name = BLOCKS[(round_num - 1) % len(BLOCKS)]
        panel = select_diverse_actors(actors, limit=min(8, max(4, len(actors))), round_num=round_num)
        session_id = f"fg_round_{round_num}"

        for turn_idx, actor in enumerate(panel):
            af = actor_fields(actor)
            sent, objection = sentiment_and_objection(af["attitude_segment"])
            greet = regional_greeting(af["region_macro"])

            if af["attitude_segment"] in ("esceptico", "critico_hate"):
                msg = (
                    f"{greet} yo difiero del optimismo de la mesa: en {af['city_name']} ({af['stratum_code']}), "
                    f"pagar por adelantado en {topic} genera rechazo si no hay respaldo; "
                    "¿qué garantía real existe si el proveedor o servicio incumple?"
                )
            elif af["attitude_segment"] == "promotor":
                msg = (
                    f"{greet} escuchando a los demás en la mesa, creo que {topic} sí aporta valor real "
                    "cuando da orden, seguimiento claro y evita riesgos o pérdidas de tiempo."
                )
            else:
                msg = (
                    f"{greet} en {af['stratum_code']} de {af['city_name']} depende mucho de si el precio o comisión "
                    "es justo frente a las alternativas tradicionales del mercado."
                )

            ts = now_iso()
            result["focus_group_turns"].append(
                {
                    "session_id": session_id,
                    "block_name": block_name,
                    "round_num": round_num,
                    "turn_index": turn_idx,
                    "actor_agent_id": af["actor_agent_id"],
                    "actor_name": af["actor_name"],
                    "city_divipola": af["city_divipola"],
                    "city_name": af["city_name"],
                    "stratum_code": af["stratum_code"],
                    "region_macro": af["region_macro"],
                    "attitude_segment": af["attitude_segment"],
                    "content_text": msg,
                    "objection_tag": objection,
                    "consensus_signal": sent,
                    "created_at": ts,
                }
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="FOCUS_GROUP_INTERVENTION",
                    content_text=msg,
                    metadata={"session_id": session_id, "block_name": block_name, "turn_index": turn_idx},
                )
            )
        return result
