"""Pruebas de Fase 5 (Gate G5): ReportAgentV2 (12 capítulos, 0 contradicciones numéricas) y endpoints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.channels import CANONICAL_CHANNEL_IDS
from app.channels.engine import ChannelSimulationEngine
from app.config import Config
from app.services.report_agent_v2 import ReportAgentV2, verify_numeric_consistency
from app.services.survey_engine import SurveyEngine


def test_report_agent_v2_generates_12_chapters_with_strict_numeric_consistency(tmp_path: Path):
    sim_id = "sim_phase5_report"
    report_id = "report_phase5_12ch"
    sim_dir = Path(tmp_path) / "simulations" / sim_id

    SurveyEngine(country_code="co").run_survey(simulation_id=sim_id, sim_dir=sim_dir, sample_size=60, use_llm=False)
    ChannelSimulationEngine(simulation_id=sim_id, sim_dir=sim_dir, country_code="co").run_rounds(
        enabled_channels=CANONICAL_CHANNEL_IDS, rounds=2
    )

    with patch.object(Config, "OASIS_SIMULATION_DATA_DIR", str(Path(tmp_path) / "simulations")), patch.object(
        Config, "UPLOAD_FOLDER", str(tmp_path)
    ):
        res = ReportAgentV2(use_llm=False).generate_report(
            report_id=report_id,
            simulation_id=sim_id,
            simulation_requirement="Validar demanda Servicio A COP $70.000 para NEXO Colombia",
        )

        chapters = res["chapters"]
        assert len(chapters) == 12
        full_md = res["markdown_content"]
        assert "ESOMAR" in chapters[1]["content_markdown"]
        assert "Van Westendorp" in chapters[5]["content_markdown"]
        assert "Economía Unitaria" in chapters[5]["content_markdown"]
        assert "funnel_finance" in chapters[8]["content_markdown"]
        assert "FO (" in chapters[10]["content_markdown"] and "DA (" in chapters[10]["content_markdown"]
        assert "SMART" in chapters[10]["content_markdown"]
        assert "100.0%" in full_md

        for ch in chapters:
            check = verify_numeric_consistency(ch["content_markdown"], ch["metrics_payload"])
            assert check["consistent"] is True

        # Endpoints REST /manifest y /chapter/<1..12>
        app = create_app()
        client = app.test_client()
        r_man = client.get(f"/api/report/{report_id}/manifest")
        assert r_man.status_code == 200
        assert len(r_man.get_json()["data"]["chapters"]) == 12

        for num in range(1, 13):
            r_ch = client.get(f"/api/report/{report_id}/chapter/{num}")
            assert r_ch.status_code == 200
            assert r_ch.get_json()["data"]["chapter_number"] == num


def test_numeric_consistency_detector_flags_contradiction():
    bad_md = "La cobertura del estudio fue 72.5% y el óptimo Gabor-Granger fue COP $999.000."
    metrics = {"db_coverage_pct": 100.0, "optimal_price": 70000.0}
    res = verify_numeric_consistency(bad_md, metrics)
    assert res["consistent"] is False
    assert len(res["mismatches"]) == 2


def test_historical_report_6d4a2701feb3_manifest_fallback_http_200():
    app = create_app()
    client = app.test_client()
    r = client.get("/api/report/report_6d4a2701feb3/manifest")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data["report_id"] == "report_6d4a2701feb3"
    assert len(data["chapters"]) >= 2
