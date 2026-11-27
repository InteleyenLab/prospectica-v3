"""Adaptador 8: Web Colombiana (Landing, NIT, Ley 1581, PSE/Nequi y fricción móvil)."""

from __future__ import annotations

from typing import Any, Dict, List

from ..base import ChannelAdapter, ChannelConfig, ChannelRegistry, InteractionTopology
from ._helpers import actor_fields, build_event, empty_result, select_diverse_actors


@ChannelRegistry.register
class ColombianWebAdapter(ChannelAdapter):
    config = ChannelConfig(
        channel_id="colombian_web",
        display_name="Web Colombiana (Landing y señales de confianza)",
        category="web_conversion",
        topology=InteractionTopology.WEB_FUNNEL,
        supports_media_exposure=False,
        description="Audita navegación en landing, verificación de NIT/RUT, Ley 1581 y botón WhatsApp/PSE.",
        peak_hours=[9, 10, 14, 15, 19, 20, 21],
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
        for actor in sample:
            af = actor_fields(actor)
            is_critic = af["attitude_segment"] in ("esceptico", "critico_hate")
            if is_critic:
                msg = (
                    f"Revisando la web desde {af['city_name']} ({af['stratum_code']}): si no aparece visible el NIT, "
                    "aviso de privacidad Ley 1581 y términos del servicio antes de pedir datos, cierro la pestaña."
                )
            else:
                msg = (
                    f"En {af['city_name']} la página carga bien en datos móviles; me dio confianza ver enlace directo "
                    "a WhatsApp Business y pago con PSE."
                )
            result["events"].append(
                build_event(
                    actor=actor,
                    channel_id=self.config.channel_id,
                    round_num=round_num,
                    simulated_hour=simulated_hour,
                    action_type="WEB_TRUST_AUDIT",
                    content_text=msg,
                    metadata={"checks": ["NIT", "Ley_1581", "WhatsApp_Business", "PSE"]},
                )
            )
        return result
