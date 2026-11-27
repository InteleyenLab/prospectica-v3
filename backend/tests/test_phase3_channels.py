"""Pruebas de Fase 3 (Gate G3) para los 11 canales colombianos + legado OASIS y SQLite WAL."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from app.channels import CANONICAL_CHANNEL_IDS, LEGACY_CHANNEL_IDS, ChannelRegistry, ZepChannelBridge
from app.channels.engine import ChannelSimulationEngine

MEDIA_EXPOSURE_CHANNELS = {"advertising", "tv", "radio", "tiktok", "instagram", "news_portals"}


@pytest.mark.parametrize("channel_id", CANONICAL_CHANNEL_IDS + LEGACY_CHANNEL_IDS)
def test_each_channel_adapter_emits_valid_events_and_spanish_zep(tmp_path: Path, channel_id: str):
    sim_dir = tmp_path / f"sim_{channel_id}"
    engine = ChannelSimulationEngine(simulation_id=f"sim_{channel_id}", sim_dir=sim_dir, country_code="co")
    actors = engine.load_actors(fallback_count=18)

    adapter = ChannelRegistry.get(channel_id)
    out = adapter.simulate_round(
        actors=actors,
        study_context={"topic_short": "Orientación inicial NEXO COP $70.000"},
        round_num=1,
        simulated_hour=19,
    )
    events = out["events"]
    assert len(events) >= 2
    for ev in events:
        assert ev.channel_id == channel_id
        assert ev.city_divipola and len(ev.city_divipola) == 5
        assert ev.stratum_code
        assert ev.content_text.strip()
        ep = ZepChannelBridge.format_episode(ev)
        assert not re.search(r"[\u4e00-\u9fff]", ep)

    if channel_id in MEDIA_EXPOSURE_CHANNELS:
        assert len(out["media_exposures"]) >= 2
    if channel_id == "whatsapp_1on1":
        assert len(out["whatsapp_sessions"]) >= 3
        assert any(s["message_type"] == "voice_note" for s in out["whatsapp_sessions"])
    if channel_id == "focus_group":
        assert len(out["focus_group_turns"]) >= 4
    if channel_id == "street_survey":
        assert len(out["survey_responses"]) >= 3


def test_full_11_channel_run_persists_5_sqlite_wal_tables_with_regional_and_critical_diversity(tmp_path: Path):
    sim_id = "sim_phase3_full"
    sim_dir = tmp_path / sim_id
    engine = ChannelSimulationEngine(simulation_id=sim_id, sim_dir=sim_dir, country_code="co")
    summary = engine.run_rounds(enabled_channels=CANONICAL_CHANNEL_IDS, rounds=2)

    assert len(summary["channels_executed"]) == 11
    assert summary["totals"]["events"] >= 40
    assert (sim_dir / "simulation_channels.db").exists()

    for cid in CANONICAL_CHANNEL_IDS:
        assert (sim_dir / "channels" / cid / "actions.jsonl").exists()

    conn = sqlite3.connect(str(sim_dir / "simulation_channels.db"))
    try:
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {
            "channel_events",
            "whatsapp_sessions",
            "focus_group_turns",
            "survey_responses",
            "media_exposures",
        }.issubset(tables)

        wa_rows = conn.execute("SELECT region_macro, objection_tag FROM whatsapp_sessions").fetchall()
        fg_rows = conn.execute("SELECT region_macro, objection_tag FROM focus_group_turns").fetchall()
        assert len({r[0] for r in wa_rows + fg_rows}) >= 3
        obj_ratio = sum(1 for r in wa_rows + fg_rows if r[1]) / len(wa_rows + fg_rows)
        assert obj_ratio >= 0.30
    finally:
        conn.close()
