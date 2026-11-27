"""Adaptador 9: Publicidad digital, OOH (vallas) y volantes impresos."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, now_iso, select_diverse_actors

AD_FORMATS = ["digital_banner", "ooh_valla", "volante_impreso"]


@ChannelRegistry.register
class AdvertisingAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="advertising",
        display_name="Publicidad (Banners, Vallas OOH y Volantes)",
        category="pauta_publicitaria",
        topology=InteractionTopology.BROADCAST_MEDIA,
        supports_media_exposure=True,
        description="Pre-test de piezas publicitarias evaluando recordación, comprensión y rechazo de promesas prohibidas.",
        peak_hours=[8, 12, 17, 18, 19, 20],
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
        for idx, actor in enumerate(sample):
            af = actor_fields(actor)
            fmt = AD_FORMATS[(idx + round_num) % len(AD_FORMATS)]
            is_critic = af["attitude_segment"] in ("esceptico", "critico_hate")
            msg = (
                f"[{fmt} en {af['city_name']}] La propuesta de {topic} suena seria si muestra respaldo real; "
                "si prometieran resultados garantizados sin condiciones lo rechazaría por engañoso."
                if is_critic
                else f"[{fmt} en {af['city_name']}] Se entiende claro cómo funciona {topic} y cuál es el beneficio desde el primer contacto."
            )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="AD_COPY_EVALUATION",
                    content_text=msg,
                    metadata={"piece_format": fmt},
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
                    "piece_format": fmt,
                    "time_slot": f"{simulated_hour:02d}:00",
                    "recall_score": 0.65,
                    "comprehension_score": 0.78,
                    "credibility_score": 0.45 if is_critic else 0.82,
                    "prohibited_promise_rejected": True,
                    "reaction_text": msg,
                    "created_at": ts,
                }
            )
        return result
