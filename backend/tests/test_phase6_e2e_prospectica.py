"""Pruebas integrales E2E de Fase 6 (Gate G6): Marca Prospéctica Inc., NEXO 7 Etapas, Consumo Masivo CO y no regresión."""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from unittest.mock import patch

from app import create_app
from app.channels import CANONICAL_CHANNEL_IDS
from app.channels.engine import ChannelSimulationEngine
from app.config import Config
from app.config_brand import BRAND_NAME, BRAND_REPORT_HEADER, BRAND_SLUG
from app.services.analytics import AnalyticsBundleBuilder
from app.services.context_fusion import ContextFusionService
from app.services.demographic_sampler import DemographicSampler
from app.services.multimodal_extractor import MultimodalExtractor
from app.services.oasis_profile_generator import OasisProfileGenerator
from app.services.report_agent_v2 import ReportAgentV2, verify_numeric_consistency
from app.services.survey_engine import SurveyEngine
from app.services.zep_entity_reader import EntityNode
from app.swarm import SwarmOrchestrator
from country_packs import get_country_pack, list_country_packs


ROOT_DIR = Path(__file__).resolve().parents[2]
NEXO_PROJECT_DIR = ROOT_DIR / "backend" / "uploads" / "projects" / "proj_047fbadfa161"


def test_brand_migration_and_country_packs_configuration():
    assert BRAND_NAME == "Prospéctica Inc."
    assert BRAND_SLUG == "prospectica"
    assert "Prospéctica Inc." in BRAND_REPORT_HEADER

    packs = {p["country_code"]: p for p in list_country_packs()}
    assert packs["co"]["status"] == "active"
    assert packs["mx"]["status"] == "planned"
    assert get_country_pack("co").currency == "COP"


def test_e2e_case1_nexo_7_stages_on_prospectica(tmp_path: Path):
    # Etapa 1: Extracción de los 3 PDFs reales + fusión territorial 12 ciudades DIVIPOLA
    files_dir = NEXO_PROJECT_DIR / "files"
    doc_texts = {}
    for fname in ("fe5cd7ba.pdf", "da66e131.pdf", "3973ab26.pdf"):
        extracted = MultimodalExtractor.extract(str(files_dir / fname))
        doc_texts[fname] = extracted.text
    assert len(doc_texts["da66e131.pdf"]) >= 200

    nexo_cities = ["11001", "05001", "76001", "08001", "13001", "23001", "68001", "54001", "66001", "17001", "47001", "73001"]
    proj_dir = tmp_path / "proj_nexo_e2e_v2"
    proj_dir.mkdir(parents=True, exist_ok=True)
    fusion = ContextFusionService().build_and_persist(
        project_id="proj_nexo_e2e_v2",
        project_dir=proj_dir,
        country_code="co",
        target_cities=nexo_cities,
        target_strata=["E3", "E4", "E5", "E6"],
        simulation_requirement="Validar Servicio A COP $70.000 y Servicio B NEXO en 12 ciudades de Colombia",
        document_texts=list(doc_texts.values()),
        use_official_sources=False,
        use_live_web=False,
    )
    assert (proj_dir / "quant_store.sqlite").exists()
    assert len(fusion["selected_cities"]) == 12

    # Etapa 2: >= 24 personas sintéticas colombianas, 0 no humanos, 0 China, >= 40% escépticos/críticos
    entities = [
        EntityNode(uuid="trap-svc", name="Servicio A NEXO", labels=["Entity", "Service"], summary="Servicio", attributes={}),
        EntityNode(uuid="trap-wa", name="Canal WhatsApp", labels=["Entity", "Channel"], summary="Canal", attributes={}),
    ] + [
        EntityNode(
            uuid=f"nexo-actor-{i}",
            name=f"Ciudadano NEXO {i+1}",
            labels=["Entity", "Citizen"],
            summary=f"Conductor o propietario colombiano en estudio NEXO #{i+1}.",
            attributes={},
        )
        for i in range(28)
    ]
    gen = OasisProfileGenerator(
        api_key="test-key",
        base_url="http://127.0.0.1:3001/v1",
        model_name="auto",
        zep_api_key="",
        country_code="co",
        target_cities=nexo_cities,
        target_strata=["E3", "E4", "E5", "E6"],
    )
    profiles = gen.generate_profiles_from_entities(entities=entities, use_llm=False, parallel_count=4)
    assert len(profiles) >= 24
    assert all(p.source_entity_type not in {"Service", "Channel", "Claim"} for p in profiles)
    assert all(p.country not in {"中国", "China"} for p in profiles)
    assert all(p.stratum_code in {"E3", "E4", "E5", "E6"} for p in profiles)
    assert sum(1 for p in profiles if p.attitude_segment in {"esceptico", "critico_hate"}) / len(profiles) >= 0.40
    assert sum(1 for p in profiles if (p.mbti or "").upper() == "ISTJ") / len(profiles) <= 0.25

    # Etapas 3 y 4: Encuesta N=300 + Simulación multicanal 11 canales
    sim_id = "sim_nexo_e2e_v2"
    sim_dir = tmp_path / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "reddit_profiles.json").write_text(
        json.dumps([p.to_reddit_format() for p in profiles], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    survey_res = SurveyEngine(country_code="co").run_survey(
        simulation_id=sim_id,
        sim_dir=sim_dir,
        sample_size=300,
        target_cities=nexo_cities,
        target_strata=["E3", "E4", "E5", "E6"],
        use_llm=False,
    )
    assert survey_res["completed_n"] == 300

    ch_res = ChannelSimulationEngine(simulation_id=sim_id, sim_dir=sim_dir, country_code="co").run_rounds(
        enabled_channels=CANONICAL_CHANNEL_IDS,
        rounds=2,
        study_context={"topic_short": "Orientación inicial NEXO COP $70.000"},
    )
    assert len(ch_res["channels_executed"]) == 11
    assert ch_res["totals"]["whatsapp_sessions"] >= 6
    assert ch_res["totals"]["focus_group_turns"] >= 3

    # Auditoría negativa de compliance comercial en mensajes de WhatsApp
    conn = sqlite3.connect(str(sim_dir / "simulation_channels.db"))
    try:
        wa_texts = [r[0] for r in conn.execute("SELECT content_text FROM whatsapp_sessions").fetchall()]
        assert len(wa_texts) >= 6
        for txt in wa_texts:
            assert not re.search(r"indemnizaci[óo]n\s+garantizada|% de [ée]xito asegurado", txt, re.I)
    finally:
        conn.close()

    # Etapas 5 y 6: Analítica determinística (VW, GG, Embudo, Finanzas 24m)
    bundle = AnalyticsBundleBuilder().build(
        simulation_id=sim_id,
        sim_dir=sim_dir,
        project_dir=proj_dir,
        country_code="co",
        write_file=True,
    )
    vw = bundle["pricing_econometrics"]["van_westendorp"]
    gg = bundle["pricing_econometrics"]["gabor_granger"]
    assert vw["pmc"] <= min(vw["opp"], vw["idp"]) <= max(vw["opp"], vw["idp"]) <= vw["pme"]
    assert gg["optimal_price"] > 0

    fin = bundle["funnel_finance"]
    assert fin["currency"] == "COP"
    assert sum(s["probability_pct"] for s in fin["scenarios"]) == 100.0
    assert len(fin["projection_24m"]["monthly_m1_m12"]) == 12
    assert len(fin["projection_24m"]["quarterly_m13_m24"]) == 4
    regs = " ".join(r["norm"] + " " + r["warning"] for r in fin["regulatory_and_legal_warnings"])
    assert "1581" in regs and "1480" in regs

    # Etapa 7: Informe 12 capítulos con marca Prospéctica Inc. y consola Orkas
    with patch.object(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations")), patch.object(
        Config, "UPLOAD_FOLDER", str(tmp_path)
    ):
        rep = ReportAgentV2(use_llm=False).generate_report(
            report_id="report_nexo_e2e_v2",
            simulation_id=sim_id,
            simulation_requirement="Estudio NEXO Colombia 7 Etapas",
            bundle=bundle,
        )
        assert len(rep["chapters"]) == 12
        assert rep["manifest"]["brand"] == "Prospéctica Inc."
        assert rep["manifest"]["data_audit"]["db_coverage_pct"] == 100.0
        for ch in rep["chapters"]:
            assert verify_numeric_consistency(ch["content_markdown"], ch["metrics_payload"])["consistent"] is True

        orch = SwarmOrchestrator(sim_id, sim_dir, use_llm=False)
        orch.create_or_get_session("sess_nexo_e2e")
        turn = orch.send_message("sess_nexo_e2e", "Resume por qué dudan en pagar $70.000")
        assert len(turn["replies"]) >= 1


def test_e2e_case2_consumo_masivo_vitalguayaba_colombia(tmp_path: Path):
    target_cities = ["11001", "05001", "76001", "08001", "68001", "52001", "27001"]
    target_strata = ["E1", "E2", "E3", "E4", "E5"]

    allocs = DemographicSampler("co").sample_allocations(
        count=35,
        country_code="co",
        target_cities=target_cities,
        target_strata=target_strata,
    )
    assert len(allocs) == 35
    sampled_codes = {a.divipola_code for a in allocs}
    assert "52001" in sampled_codes  # Pasto
    assert "27001" in sampled_codes  # Quibdó

    sim_id = "sim_vitalguayaba_co"
    sim_dir = tmp_path / "simulations" / sim_id
    sim_dir.mkdir(parents=True, exist_ok=True)
    survey = SurveyEngine("co").run_survey(
        simulation_id=sim_id,
        sim_dir=sim_dir,
        sample_size=300,
        target_cities=target_cities,
        target_strata=target_strata,
        use_llm=False,
    )
    assert survey["completed_n"] == 300

    ch_summary = ChannelSimulationEngine(sim_id, sim_dir, country_code="co").run_rounds(
        enabled_channels=["street_survey", "whatsapp_1on1", "radio", "tv", "focus_group", "tiktok"],
        rounds=2,
        study_context={"topic_short": "VitalGuayaba bebida funcional 300ml"},
    )
    assert ch_summary["totals"]["events"] >= 12

    bundle = AnalyticsBundleBuilder().build(
        simulation_id=sim_id,
        sim_dir=sim_dir,
        country_code="co",
        write_file=True,
    )
    assert bundle["data_audit"]["db_coverage_pct"] == 100.0

    with patch.object(Config, "OASIS_SIMULATION_DATA_DIR", str(tmp_path / "simulations")), patch.object(
        Config, "UPLOAD_FOLDER", str(tmp_path)
    ):
        rep = ReportAgentV2(use_llm=False).generate_report(
            report_id="report_vitalguayaba_co",
            simulation_id=sim_id,
            simulation_requirement="Validación consumo masivo VitalGuayaba en 7 ciudades CO",
            bundle=bundle,
        )
        assert len(rep["chapters"]) == 12
        assert rep["manifest"]["brand"] == "Prospéctica Inc."


def test_historical_artifacts_no_regression_after_brand_migration():
    app = create_app()
    client = app.test_client()
    for path in (
        "/api/graph/project/proj_047fbadfa161",
        "/api/report/report_6d4a2701feb3/manifest",
        "/api/analytics/sim_345b78a4490f/bundle",
        "/api/swarm/sim_345b78a4490f/sessions",
    ):
        resp = client.get(path)
        assert resp.status_code == 200, f"Fallo en endpoint histórico {path}"
