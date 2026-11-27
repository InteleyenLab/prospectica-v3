"""Orquestador de rondas multicanal sobre `simulation_channels.db` y JSONL."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..services.demographic_sampler import DemographicSampler
from . import adapters as _loaded_adapters  # noqa: F401 - registra los 11 + legado
from .base import CANONICAL_CHANNEL_IDS, ChannelRegistry
from .persistence import ChannelSQLiteStore
from .zep_bridge import ZepChannelBridge


class ChannelSimulationEngine:
    """Ejecuta rondas multicanal por franja horaria colombiana y persiste las 5 tablas WAL."""

    def __init__(self, simulation_id: str, sim_dir: Path, country_code: str = "co"):
        self.simulation_id = simulation_id
        self.sim_dir = Path(sim_dir)
        self.country_code = country_code
        self.store = ChannelSQLiteStore(self.sim_dir)

    def load_actors(self, fallback_count: int = 24) -> List[Dict[str, Any]]:
        """Carga actores de `reddit_profiles.json`/`profiles_enriched.json` o genera muestra estratificada."""
        enriched_path = self.sim_dir / "profiles_enriched.json"
        if enriched_path.exists():
            try:
                data = json.loads(enriched_path.read_text(encoding="utf-8"))
                profiles = data.get("profiles") if isinstance(data, dict) else data
                if isinstance(profiles, list) and profiles:
                    return profiles
            except Exception:
                pass

        reddit_path = self.sim_dir / "reddit_profiles.json"
        if reddit_path.exists():
            try:
                profiles = json.loads(reddit_path.read_text(encoding="utf-8"))
                if isinstance(profiles, list) and profiles:
                    return profiles
            except Exception:
                pass

        sampler = DemographicSampler(country_code=self.country_code)
        allocs = sampler.sample_allocations(
            count=fallback_count,
            country_code=self.country_code,
            target_cities=["Bogotá", "Medellín", "Cali", "Barranquilla", "Bucaramanga"],
        )
        return [
            {
                "user_id": a.slot_index,
                "username": f"ciudadano_{a.slot_index}",
                "name": f"Ciudadano {a.city_name.split()[0]} #{a.slot_index + 1}",
                "city_name": a.city_name,
                "divipola_code": a.divipola_code,
                "stratum_code": a.stratum_code,
                "wealth_tier_norm": a.wealth_tier_norm,
                "region_macro": a.region_macro,
                "attitude_segment": a.attitude_segment,
                "dynamic_study_role": a.dynamic_study_role,
                "age": a.age,
                "gender": a.gender,
            }
            for a in allocs
        ]

    def run_rounds(
        self,
        enabled_channels: Optional[List[str]] = None,
        rounds: int = 2,
        study_context: Optional[Dict[str, Any]] = None,
        start_hour: int = 9,
    ) -> Dict[str, Any]:
        """Ejecuta `rounds` rondas sobre los canales habilitados y persiste eventos/sesiones/exposiciones."""
        channels = [c for c in (enabled_channels or CANONICAL_CHANNEL_IDS) if c in ChannelRegistry.registered_ids()]
        actors = self.load_actors()
        ctx = dict(study_context or {})

        totals: Dict[str, int] = {
            "events": 0,
            "whatsapp_sessions": 0,
            "focus_group_turns": 0,
            "survey_responses": 0,
            "media_exposures": 0,
        }
        zep_episodes: List[Dict[str, Any]] = []

        for r in range(1, max(1, rounds) + 1):
            sim_hour = (start_hour + r - 1) % 24
            for cid in channels:
                adapter = ChannelRegistry.get(cid)
                batch = adapter.simulate_round(
                    actors=actors,
                    study_context=ctx,
                    round_num=r,
                    simulated_hour=sim_hour,
                )
                for ev in batch.get("events", []):
                    self.store.record_channel_event(self.simulation_id, ev, write_jsonl=True)
                    totals["events"] += 1
                    if ZepChannelBridge.should_index(ev):
                        zep_episodes.append(
                            {
                                "channel_id": ev.channel_id,
                                "round_num": ev.round_num,
                                "episode_text": ZepChannelBridge.format_episode(ev),
                            }
                        )
                for row in batch.get("whatsapp_sessions", []):
                    self.store.record_whatsapp_session(self.simulation_id, row)
                    totals["whatsapp_sessions"] += 1
                for row in batch.get("focus_group_turns", []):
                    self.store.record_focus_group_turn(self.simulation_id, row)
                    totals["focus_group_turns"] += 1
                survey_rows = batch.get("survey_responses", [])
                if survey_rows:
                    totals["survey_responses"] += self.store.record_survey_responses_bulk(
                        self.simulation_id, survey_rows
                    )
                for row in batch.get("media_exposures", []):
                    self.store.record_media_exposure(self.simulation_id, row)
                    totals["media_exposures"] += 1

        return {
            "simulation_id": self.simulation_id,
            "channels_executed": channels,
            "rounds_completed": rounds,
            "totals": totals,
            "zep_episodes_count": len(zep_episodes),
            "db_path": str(self.store.db_path),
        }
