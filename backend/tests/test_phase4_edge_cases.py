"""Pruebas de Fase 4: edge cases ESOMAR/ISO, cobertura 100%, rendimiento <10s y API /bundle."""

from __future__ import annotations

import time
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.channels import CANONICAL_CHANNEL_IDS
from app.channels.engine import ChannelSimulationEngine
from app.config import Config
from app.services.analytics import AnalyticsBundleBuilder
from app.services.analytics.cx_and_polarization import CXAndPolarizationEngine
from app.services.analytics.pricing_econometrics import compute_gabor_granger, compute_van_westendorp
from app.services.analytics.weighting_and_stats import anova_or_kruskal, chi2_or_fisher, welch_t_and_cohen_d
from app.services.survey_engine import SurveyEngine


def test_esomar_iso_edge_cases():
    # 1. Filtrado estricto de VW no monotónico sin imputar
    vw = compute_van_westendorp(
        [
            {"vw_too_cheap": 80000, "vw_cheap": 40000, "vw_expensive": 90000, "vw_too_expensive": 120000},  # inválido
            {"vw_too_cheap": 20000, "vw_cheap": 40000, "vw_expensive": 70000, "vw_too_expensive": 100000},  # válido
        ]
    )
    assert vw["total_n"] == 2
    assert vw["valid_n"] == 1
    assert vw["discarded_non_monotonic"] == 1
    assert abs(vw["consistency_rate"] - 0.5) < 1e-6

    # 2. Bloqueo paramétrico cuando subgrupo n < 15
    assert welch_t_and_cohen_d([1, 2, 3], [4, 5, 6] * 3)["parametric_blocked"] is True
    assert anova_or_kruskal({"A": [1, 2, 3], "B": [4] * 20})["parametric_blocked"] is True

    # 3. Fallback a prueba exacta de Fisher cuando >20% celdas E_ij < 5
    res_fisher = chi2_or_fisher([[1, 4], [4, 1]])
    assert res_fisher["test_used"] == "fisher_exact"

    # 4. Sycophancy warning (>85% positivo o Pol < 0.15) + bimodal alert
    cx = CXAndPolarizationEngine().analyze(
        [
            {"status": "completed", "nps_score": 10, "csat_score": 5, "ces_score": 7, "trust_score": 9}
            for _ in range(20)
        ]
    )
    assert cx["sycophancy_warning"] is True

    # 5. Suavizado isotónico PAV en Gabor-Granger con inversión muestral
    gg_non_mono = compute_gabor_granger(
        [{"gg_grid": {"30000": 0.60, "50000": 0.80, "80000": 0.30}}]
    )
    assert gg_non_mono["isotonic_applied"] is True
    qs = [pt["demand_monotonic"] for pt in gg_non_mono["points"]]
    assert qs[0] >= qs[1] >= qs[2]


def test_full_pipeline_100_percent_coverage_performance_and_api(tmp_path: Path):
    sim_id = "sim_phase4_bench"
    sim_dir = tmp_path / sim_id

    # Poblar encuesta N=300 + >= 2000 eventos multicanal
    SurveyEngine(country_code="co").run_survey(
        simulation_id=sim_id,
        sim_dir=sim_dir,
        sample_size=300,
        use_llm=False,
    )
    ChannelSimulationEngine(simulation_id=sim_id, sim_dir=sim_dir, country_code="co").run_rounds(
        enabled_channels=CANONICAL_CHANNEL_IDS,
        rounds=38,
    )

    t0 = time.monotonic()
    bundle = AnalyticsBundleBuilder().build(
        simulation_id=sim_id,
        sim_dir=sim_dir,
        country_code="co",
        write_file=True,
    )
    elapsed = time.monotonic() - t0

    assert elapsed < 10.0
    assert (sim_dir / "analytics_bundle.json").exists()
    audit = bundle["data_audit"]
    assert audit["db_coverage_pct"] == 100.0
    # 300 encuestas estructuradas + 228 interceptaciones de street_survey (6 x 38 rondas) = 528 totales
    assert audit["surveys_analyzed"] == audit["total_surveys_db"] == 528
    assert audit["events_analyzed"] == audit["total_events_db"] >= 2000
    assert set(bundle["chapter_slices"].keys()) == {f"{i:02d}" for i in range(1, 13)}

    # Verificar endpoints HTTP 200 /api/analytics/<sim_id>/run y /bundle
    app = create_app()
    client = app.test_client()
    with patch.object(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path)):
        r_run = client.post(f"/api/analytics/{sim_id}/run")
        assert r_run.status_code == 200
        assert r_run.get_json()["success"] is True

        r_bundle = client.get(f"/api/analytics/{sim_id}/bundle")
        assert r_bundle.status_code == 200
        assert r_bundle.get_json()["data"]["sha256_hash"]

        r_ch09 = client.get(f"/api/analytics/{sim_id}/bundle?chapter=9")
        assert r_ch09.status_code == 200
        assert "finance" in r_ch09.get_json()["data"]["slice"]

    # Modo legado sim_345b78a4490f sin fallar por ausencia de encuestas VW/GG
    r_leg = client.get("/api/analytics/sim_345b78a4490f/bundle")
    assert r_leg.status_code == 200
    leg_data = r_leg.get_json()["data"]
    assert leg_data["pricing_econometrics"]["van_westendorp"]["status"] == "not_applicable_legacy"
