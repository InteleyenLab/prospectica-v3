"""Pruebas de Fase 3 para el motor de encuestas estructuradas (N=300 y smoke test en vivo N=30)."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.config import Config
from app.services.survey_engine import SurveyEngine


def test_survey_endpoint_runs_n300_without_timeout_or_413(tmp_path: Path):
    app = create_app()
    client = app.test_client()
    sim_id = "sim_survey_300"

    with patch.object(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path)):
        resp = client.post(
            f"/api/swarm/{sim_id}/survey/run",
            json={"sample_size": 300, "use_llm": False, "sync": True},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["success"] is True
        res = payload["data"]["result"]
        assert res["completed_n"] == 300

        task_id = payload["data"]["task_id"]
        t_resp = client.get(f"/api/swarm/{sim_id}/tasks/{task_id}")
        assert t_resp.status_code == 200
        assert t_resp.get_json()["data"]["status"] == "completed"

        db_path = Path(tmp_path) / sim_id / "simulation_channels.db"
        conn = sqlite3.connect(str(db_path))
        try:
            rows = conn.execute(
                "SELECT vw_too_cheap, vw_cheap, vw_expensive, vw_too_expensive, gg_grid_json FROM survey_responses"
            ).fetchall()
            assert len(rows) == 300
            for tc, c, e, te, gg_raw in rows:
                assert tc < c < e < te
                gg = json.loads(gg_raw)
                assert len(gg) == 5
        finally:
            conn.close()


def test_live_llm_survey_smoke_n30_under_180s(tmp_path: Path):
    """Smoke test real en vivo N=30 contra FreeLLMAPI (`127.0.0.1:3001/v1`) en <180s."""
    sim_id = "sim_survey_smoke_30"
    engine = SurveyEngine(country_code="co")

    t0 = time.monotonic()
    res = engine.run_survey(
        simulation_id=sim_id,
        sim_dir=tmp_path / sim_id,
        sample_size=30,
        target_cities=["Bogotá", "Medellín", "Cali"],
        use_llm=True,
        batch_size=10,
        max_workers=3,
    )
    elapsed = time.monotonic() - t0
    assert elapsed < 180.0
    assert res["completed_n"] == 30

    conn = sqlite3.connect(str(Path(res["db_path"])))
    try:
        cnt = conn.execute("SELECT COUNT(*) FROM survey_responses WHERE status='completed'").fetchone()[0]
        assert cnt == 30
    finally:
        conn.close()
