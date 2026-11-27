"""Adaptador 1: WhatsApp 1-a-1 con notas de voz simuladas y fricción Nequi/Daviplata/PSE."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, regional_greeting, select_diverse_actors, sentiment_and_objection


@ChannelRegistry.register
class WhatsApp1on1Adapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="whatsapp_1on1",
        display_name="WhatsApp 1-a-1 (Notas de voz y conversión)",
        category="conversacional",
        topology=InteractionTopology.PRIVATE_THREAD,
        supports_media_exposure=False,
        description="Simula conversaciones privadas 1-a-1, audios transcritos y fricciones de pago Nequi/Daviplata/PSE.",
        peak_hours=[7, 8, 9, 12, 13, 18, 19, 20, 21],
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
        sample = select_diverse_actors(actors, limit=min(6, max(3, len(actors))), round_num=round_num)

        for idx, actor in enumerate(sample):
            af = actor_fields(actor)
            _, objection = sentiment_and_objection(af["attitude_segment"])
            greet = regional_greeting(af["region_macro"], slot_index=idx)
            is_voice = idx % 2 == 1
            payment_method = ["Nequi", "Daviplata", "PSE", "efectivo/Efecty"][idx % 4]
            friction_tag = (
                f"desconfianza_transferencia_{payment_method}"
                if af["attitude_segment"] in ("esceptico", "critico_hate")
                else "consulta_enlace_pse"
            )

            if af["attitude_segment"] in ("esceptico", "critico_hate"):
                msg = (
                    f"{greet} me piden pagar o usar {payment_method} para {topic}, "
                    f"pero aquí en {af['city_name']} uno ve mucho tumbe. ¿Dónde está el NIT, los términos claros "
                    "y quién responde si algo no sale como prometen?"
                )
            elif af["attitude_segment"] == "promotor":
                msg = (
                    f"{greet} sí me interesa usar {topic} si me da claridad y respaldo real. "
                    f"Si aceptan {payment_method} y atienden rápido por WhatsApp, le hago."
                )
            else:
                msg = (
                    f"{greet} ¿el valor o tarifa de {topic} incluye todo el proceso o después cobran cargos ocultos? "
                    f"Prefiero saber antes de transferir por {payment_method}."
                )

            session_key = f"wa_{af['actor_agent_id']}_{af['city_divipola']}"
            ts = now_iso()
            result["whatsapp_sessions"].append(
                {
                    "session_key": session_key,
                    "actor_agent_id": af["actor_agent_id"],
                    "actor_name": af["actor_name"],
                    "city_divipola": af["city_divipola"],
                    "city_name": af["city_name"],
                    "stratum_code": af["stratum_code"],
                    "region_macro": af["region_macro"],
                    "round_num": round_num,
                    "message_role": "citizen",
                    "message_type": "voice_note" if is_voice else "text",
                    "content_text": msg,
                    "audio_transcript": msg if is_voice else None,
                    "duration_sec": (18 + idx * 5) if is_voice else 0,
                    "payment_friction_tag": friction_tag,
                    "objection_tag": objection,
                    "created_at": ts,
                }
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="WHATSAPP_VOICE_NOTE" if is_voice else "WHATSAPP_MESSAGE",
                    content_text=msg,
                    metadata={
                        "session_key": session_key,
                        "message_type": "voice_note" if is_voice else "text",
                        "payment_friction_tag": friction_tag,
                    },
                )
            )
        return result
