"""Pruebas API de Fase 3 para /api/channels/* y retrocompatibilidad con sim_345b78a4490f."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.config import Config


def test_channels_api_catalog_events_sessions_and_legacy_sim(tmp_path: Path):
    app = create_app()
    client = app.test_client()

    # 1. Catálogo completo de 11 canales + 2 legados
    r_cat = client.get("/api/channels/catalog")
    assert r_cat.status_code == 200
    data = r_cat.get_json()
    assert data["success"] is True
    assert data["count"] >= 13

    # 2. Ejecución multicanal y consulta de eventos/sesiones
    sim_id = "sim_api_chan_test"
    with patch.object(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path)):
        r_run = client.post(
            f"/api/channels/{sim_id}/run",
            json={"rounds": 1},
        )
        assert r_run.status_code == 200
        assert len(r_run.get_json()["data"]["channels_executed"]) == 11

        r_ev = client.get(f"/api/channels/{sim_id}/events?channel_id=whatsapp_1on1")
        assert r_ev.status_code == 200
        assert r_ev.get_json()["data"]["count"] >= 3

        r_sess = client.get(f"/api/channels/{sim_id}/sessions/focus_group")
        assert r_sess.status_code == 200
        assert len(r_sess.get_json()["data"]["items"]) >= 4

    # 3. No regresión en sim_345b78a4490f (legado)
    r_legacy_detail = client.get("/api/simulation/sim_345b78a4490f/run-status/detail")
    assert r_legacy_detail.status_code == 200
    assert r_legacy_detail.get_json()["success"] is True

    r_legacy_events = client.get("/api/channels/sim_345b78a4490f/events?limit=10")
    assert r_legacy_events.status_code == 200
    assert r_legacy_events.get_json()["success"] is True
