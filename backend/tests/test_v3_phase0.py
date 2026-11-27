"""Pruebas unitarias e integración de Fase 0 (Prospéctica V3 - Corrección P0)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import create_app
from app.services.analytics.funnel_finance import FunnelFinanceEngine
from app.services.compliance import (
    SYNTHETIC_DISCLOSURE_NOTICE,
    record_consent,
    redact_pii,
    scan_pii,
)
from app.services.secondary_research import SecondaryResearchEngine
from app.services.study_context_builder import (
    confirm_study_context,
    extract_and_build_study_context,
)
from app.services.survey_engine import SurveyEngine
from app.services.validators import ReportValidator


def _build_valid_bundle() -> tuple[dict, dict]:
    sctx = extract_and_build_study_context(
        project_id="proj_p0_valid",
        project_name_hint="COFRE",
        extracted_text=(
            "COFRE es un marketplace financiero en Colombia con modelo de comisión sobre recaudo "
            "(2.5% a 5.0% por transacción) para comercios aliados y usuarios en Bogotá y Medellín."
        ),
        simulation_requirement="Validar viabilidad comercial de COFRE en Colombia",
        use_llm=False,
    )
    confirm_study_context("proj_p0_valid", confirmed_by="analista_test")
    sec = SecondaryResearchEngine().run(sctx)
    fin = FunnelFinanceEngine().analyze(
        country_code="co",
        optimal_price_a=70000.0,
        conversion_rate_probable=0.08,
    )
    return {
        "simulation_id": "sim_p0_valid",
        "country_code": "co",
        "data_audit": {
            "db_coverage_pct": 100.0,
            "surveys_analyzed": 300,
            "events_analyzed": 120,
            "agents_analyzed": 80,
        },
        "pricing_econometrics": {
            "van_westendorp": {"pmc": 35000.0, "opp": 52000.0, "idp": 65000.0, "pme": 110000.0},
            "gabor_granger": {"optimal_price": 70000.0},
        },
        "cx_and_polarization": {
            "nps": {"nps": 22.0, "promoters_pct": 42.0, "passives_pct": 38.0, "detractors_pct": 20.0},
            "polarization": {"consensus": 0.61, "polarization": 0.39},
            "bimodality": {"bc": 0.42},
        },
        "funnel_and_cdj": {
            "funnel_stages": [
                {"stage": "Awareness", "count": 100, "share_of_total_pct": 100.0, "step_conversion_rate": 1.0},
                {"stage": "Consideration", "count": 72, "share_of_total_pct": 72.0, "step_conversion_rate": 0.72},
                {"stage": "Trial_Intent", "count": 48, "share_of_total_pct": 48.0, "step_conversion_rate": 0.667},
                {"stage": "Adoption", "count": 28, "share_of_total_pct": 28.0, "step_conversion_rate": 0.583},
                {"stage": "Advocacy", "count": 14, "share_of_total_pct": 14.0, "step_conversion_rate": 0.5},
            ],
            "cdj_channel_loops": [
                {"channel_id": "whatsapp_1on1", "touchpoints": 40, "friction_events": 12, "friction_rate": 0.30},
                {"channel_id": "instagram", "touchpoints": 30, "friction_events": 14, "friction_rate": 0.467},
                {"channel_id": "facebook_groups", "touchpoints": 25, "friction_events": 15, "friction_rate": 0.60},
            ],
        },
        "funnel_finance": fin,
        "secondary_research": sec,
        "sha256_hash": "a" * 64,
    }, sctx


def test_p0_study_context_commission_model_and_confirmation(tmp_path: Path):
    sctx = extract_and_build_study_context(
        project_id="proj_cofre_p0",
        project_name_hint="COFRE",
        extracted_text="COFRE cobra comisión del 2.5% por cada venta recaudada en comercios aliados de Colombia.",
        simulation_requirement="Estudio de mercado para COFRE en Colombia",
        use_llm=False,
        project_dir=tmp_path,
    )
    assert sctx["business_model_template"]["revenue_mechanism"] == "comision_pct"
    assert sctx["business_model_template"]["commission_ladder_pct"]
    assert sctx["confirmed"] is False

    confirmed = confirm_study_context(
        "proj_cofre_p0",
        updates={"business_model_template": {"who_pays": "Comercios aliados"}},
        confirmed_by="director_comercial",
        project_dir=tmp_path,
    )
    assert confirmed is not None
    assert confirmed["confirmed"] is True
    assert confirmed["confirmed_by"] == "director_comercial"
    assert confirmed["business_model_template"]["who_pays"] == "Comercios aliados"


def test_p0_secondary_research_tam_sam_som_and_competitors(tmp_path: Path):
    sctx = extract_and_build_study_context(
        project_id="proj_sec_p0",
        project_name_hint="FacturaPyme",
        extracted_text="Plataforma B2B SaaS de facturación electrónica para pymes colombianas.",
        simulation_requirement="Validar adopción SaaS pymes",
        use_llm=False,
        project_dir=tmp_path,
    )
    res = SecondaryResearchEngine().run(sctx, project_dir=tmp_path)
    tam = res["tam_sam_som"]["top_down"]
    assert tam["tam"]["probable"] >= tam["sam"]["probable"] >= tam["som"]["probable"] > 0
    assert res["tam_sam_som"]["triangulation_within_3x"] is True
    assert len(res["competitor_matrix"]) >= 8
    assert res["sources_count"] >= 10
    assert (tmp_path / "evidence_ledger.json").exists()


def test_p0_monte_carlo_5000_and_unit_economics():
    fin = FunnelFinanceEngine().analyze(country_code="co", optimal_price_a=70000.0)
    mc = fin["monte_carlo"]
    assert mc["runs"] == 5000
    rev = mc["revenue_24m_percentiles"]
    assert rev["p10"] <= rev["p50"] <= rev["p90"]
    ue = fin["unit_economics_ranges"]
    assert ue["ltv"]["probable"] > 0
    assert ue["ltv_cac_ratio"]["probable"] > 0
    assert ue["payback_months"]["probable"] > 0
    assert fin["financial_semaphore"] in ("verde", "ambar", "rojo")
    assert len(fin["reconciliation_table"]) >= 2


def test_p0_survey_engine_supports_commission_pct(tmp_path: Path):
    engine = SurveyEngine(country_code="co")
    res = engine.run_survey(
        simulation_id="sim_comm_p0",
        sim_dir=tmp_path,
        sample_size=20,
        price_ladder=[1.5, 2.5, 3.5, 5.0, 7.0],
        use_llm=False,
    )
    assert res["completed_n"] == 20
    assert res["pricing_mode"] == "comision_pct"


def test_p0_validators_pass_valid_and_block_mutations():
    bundle, sctx = _build_valid_bundle()
    valid_md = f"{SYNTHETIC_DISCLOSURE_NOTICE}\n\n## Capítulo 1\nResultados [SINTÉTICO·CALIBRADO] [CALCULADO]. LTV y recurrencia verificados."
    ok = ReportValidator().validate(bundle, study_context=sctx, report_markdown=valid_md)
    assert ok["status"] == "PASS"
    assert ok["can_publish"] is True
    assert ok["total_rules"] == 45

    # Mutación V-40: lenguaje prohibido ESOMAR / ISO 20252
    bad_v40 = ReportValidator().validate(
        bundle,
        study_context=sctx,
        report_markdown="Este informe cumple con Ficha Técnica ESOMAR / ISO 20252 y margen de error ±2.1%.",
    )
    assert bad_v40["status"] == "BLOCKED"
    assert any(b["rule_id"] == "V-40" for b in bad_v40["blocking_errors"])

    # Mutación V-03: "NPS medio"
    bad_v03 = ReportValidator().validate(
        bundle,
        study_context=sctx,
        report_markdown="Tabla con NPS medio de 4.5 en estrato 3.",
    )
    assert bad_v03["status"] == "BLOCKED"
    assert any(b["rule_id"] == "V-03" for b in bad_v03["blocking_errors"])

    # Mutación V-12: etapa intermedia al 100% con fricción
    b_v12 = json.loads(json.dumps(bundle))
    b_v12["funnel_and_cdj"]["funnel_stages"][1]["share_of_total_pct"] = 100.0
    bad_v12 = ReportValidator().validate(b_v12, study_context=sctx, report_markdown=valid_md)
    assert bad_v12["status"] == "BLOCKED"
    assert any(b["rule_id"] == "V-12" for b in bad_v12["blocking_errors"])

    # Mutación V-17: PMC > PME en Van Westendorp (advertencia)
    b_v17 = json.loads(json.dumps(bundle))
    b_v17["pricing_econometrics"]["van_westendorp"]["status"] = "ok"
    b_v17["pricing_econometrics"]["van_westendorp"]["pmc"] = 150000.0
    b_v17["pricing_econometrics"]["van_westendorp"]["pme"] = 90000.0
    bad_v17 = ReportValidator().validate(b_v17, study_context=sctx, report_markdown=valid_md)
    assert any(w["rule_id"] == "V-17" for w in bad_v17["warnings"])

    # Mutación V-21: fricción 100% uniforme en todos los canales
    b_v21 = json.loads(json.dumps(bundle))
    for c in b_v21["funnel_and_cdj"]["cdj_channel_loops"]:
        c["friction_rate"] = 1.0
    bad_v21 = ReportValidator().validate(b_v21, study_context=sctx, report_markdown=valid_md)
    assert bad_v21["status"] == "BLOCKED"
    assert any(b["rule_id"] == "V-21" for b in bad_v21["blocking_errors"])

    # Mutación V-42: categoría excluida (encuesta electoral)
    sctx_v42 = json.loads(json.dumps(sctx))
    sctx_v42["offer_summary"] = "Encuesta electoral de intención de voto presidencial"
    bad_v42 = ReportValidator().validate(bundle, study_context=sctx_v42, report_markdown=valid_md)
    assert bad_v42["status"] == "BLOCKED"
    assert any(b["rule_id"] == "V-42" for b in bad_v42["blocking_errors"])

    # Mutación V-43: PII en markdown
    assert scan_pii("Contacto: juan@ejemplo.com")[0]["type"] == "email"
    assert "[REDACTADO_" in redact_pii("Tel 3001234567")
    bad_v43 = ReportValidator().validate(
        bundle,
        study_context=sctx,
        report_markdown=valid_md + "\nEmail real: juan@empresa.co",
    )
    assert bad_v43["status"] == "BLOCKED"
    assert any(b["rule_id"] == "V-43" for b in bad_v43["blocking_errors"])


def test_p0_api_endpoints(tmp_path: Path, monkeypatch):
    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    pid = "proj_api_p0_test"
    r1 = client.post(
        "/api/brief",
        json={
            "project_id": pid,
            "brief": {
                "project_name": "NEXO",
                "description": "Plataforma de pagos recurrentes para suscripciones en Colombia.",
                "objective": "Validar adopción y precio",
            },
            "consent": {
                "accepted_privacy": True,
                "accepted_synthetic_nature": True,
                "no_unnecessary_pii": True,
            },
        },
    )
    assert r1.status_code == 200
    assert r1.get_json()["success"] is True

    r2 = client.post(
        "/api/study-context/confirm",
        json={"project_id": pid, "confirmed_by": "qa_user"},
    )
    assert r2.status_code == 200
    assert r2.get_json()["data"]["confirmed"] is True

    r3 = client.post("/api/research/secondary/run", json={"project_id": pid})
    assert r3.status_code == 200
    assert len(r3.get_json()["data"]["competitor_matrix"]) >= 8

    r4 = client.get(f"/api/research/evidence?project_id={pid}")
    assert r4.status_code == 200
    assert r4.get_json()["data"]["count"] >= 1

    bundle, sctx = _build_valid_bundle()
    r5 = client.post(
        "/api/validators/run",
        json={
            "bundle": bundle,
            "study_context": sctx,
            "report_markdown": f"{SYNTHETIC_DISCLOSURE_NOTICE}\nLTV y recurrencia.",
        },
    )
    assert r5.status_code == 200
    assert r5.get_json()["data"]["status"] == "PASS"
