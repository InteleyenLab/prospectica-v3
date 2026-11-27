"""Pruebas unitarias e integración de Fase 1 (Persona Engine V2, Calibración, Embudo Emergente y Réplicas)."""

from __future__ import annotations

from pathlib import Path

from app import create_app
from app.services.analytics.data_loader import LoadedSimulationData
from app.services.analytics.funnel_and_cdj import FunnelAndCDJEngine
from app.services.calibration import (
    COLOMBIA_ANCHORS,
    BayesianCalibrator,
    CalibrationEngine,
)
from app.services.persona_engine_v2 import PersonaEngineV2


def test_p1_persona_engine_v2_7_layers_and_diversity():
    engine = PersonaEngineV2(country_code="co")
    cohort = engine.generate_cohort(
        count=60,
        study_context={"project_name": "COFRE", "sector": "fintech"},
        seed=2026,
    )
    assert cohort["count"] == 60
    p0 = cohort["personas"][0]
    for layer in (
        "layer_1_demographics",
        "layer_2_socioeconomic",
        "layer_3_psychographics",
        "layer_4_behavioral",
        "layer_5_digital_access",
        "layer_6_domain_context",
        "layer_7_human_imperfections",
    ):
        assert layer in p0
    div = cohort["diversity_audit"]
    assert div["model_families_count"] >= 2
    assert div["max_3word_opening_share"] <= 0.15
    assert div["passed"] is True


def test_p1_calibration_anchors_gate_and_replica_stability():
    assert len(COLOMBIA_ANCHORS) >= 15
    bundle = {
        "cx_and_polarization": {"nps": {"promoters_pct": 42.0, "detractors_pct": 22.0}},
        "funnel_and_cdj": {
            "funnel_stages": [
                {"stage": "Awareness", "share_of_total_pct": 100.0},
                {"stage": "Consideration", "share_of_total_pct": 75.0},
                {"stage": "Trial_Intent", "share_of_total_pct": 50.0},
                {"stage": "Adoption", "share_of_total_pct": 30.0},
            ]
        },
    }
    gate_res = CalibrationEngine().evaluate_gate(
        bundle=bundle,
        study_context={"sector": "fintech", "geographic_scope": "Nacional"},
    )
    assert gate_res["executed"] is True
    assert gate_res["anchors_count"] >= 15
    assert gate_res["sector_geo_anchors"] >= 5
    assert gate_res["gate"] in ("APROBADO", "PARCIAL", "NO APROBADO")

    rep_res = CalibrationEngine.evaluate_replica_stability(
        [
            {"nps": 22.0, "optimal_price": 70000.0},
            {"nps": 24.5, "optimal_price": 70000.0},
            {"nps": 21.0, "optimal_price": 68000.0},
        ]
    )
    assert rep_res["replicas_count"] == 3
    assert rep_res["stable"] is True


def test_p1_bayesian_recalibration_with_real_data(tmp_path: Path):
    res = BayesianCalibrator.update_with_real_data(
        prior_conversion_rate=0.08,
        real_trials=50,
        real_conversions=10,
        project_dir=tmp_path,
        notes="Piloto real Bogotá",
    )
    assert res["observed_real_rate"] == 0.2
    assert 0.08 < res["posterior_rate"] < 0.2
    assert res["tag"] == "[REAL]"
    assert (tmp_path / "real_data_batch.json").exists()
    assert (tmp_path / "calibration_history.json").exists()


def test_p1_emergent_funnel_prevents_100pct_middle_stages():
    data = LoadedSimulationData(
        simulation_id="sim_p1_funnel",
        sim_dir=Path("."),
        is_legacy=False,
        survey_responses=[
            {"status": "completed", "pain_score": 8, "nms_intent_cheap": 4, "trust_score": 4, "nps_score": 8}
            for _ in range(20)
        ],
        channel_events=[
            {"channel_id": "whatsapp_1on1", "is_friction": True, "objection_tag": "precio"},
            {"channel_id": "instagram", "is_friction": True, "objection_tag": "confianza"},
            {"channel_id": "facebook_groups", "is_friction": True, "objection_tag": "soporte"},
        ],
        media_exposures=[],
    )
    res = FunnelAndCDJEngine().analyze(data)
    stages = res["funnel_stages"]
    assert stages[1]["share_of_total_pct"] < 100.0
    assert stages[2]["share_of_total_pct"] < 100.0
    assert not all(c["friction_rate"] == 1.0 for c in res["cdj_channel_loops"])


def test_p1_api_endpoints():
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    r1 = client.post("/api/personas/v2/generate", json={"count": 20, "seed": 99})
    assert r1.status_code == 200
    assert r1.get_json()["data"]["count"] == 20

    r2 = client.post("/api/calibration/run", json={"bundle": {}, "study_context": {"sector": "general"}})
    assert r2.status_code == 200
    assert r2.get_json()["data"]["anchors_count"] >= 15

    r3 = client.post(
        "/api/real-data/upload",
        json={"project_id": "proj_p1_api", "prior_conversion_rate": 0.1, "real_trials": 40, "real_conversions": 8},
    )
    assert r3.status_code == 200
    assert r3.get_json()["data"]["tag"] == "[REAL]"
