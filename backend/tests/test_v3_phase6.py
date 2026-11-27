"""Pruebas de Fase 6 (Flujo principal unificado ReportBuilderV3 18 capítulos + Country Packs LATAM pe/cl)."""

from __future__ import annotations

from pathlib import Path

from app import create_app
from app.services.report_agent import ReportAgent
from country_packs import get_country_pack, list_country_packs


def test_p6_country_packs_latam_pe_cl():
    packs = list_country_packs()
    codes = {p["country_code"] for p in packs}
    assert {"co", "mx", "pe", "cl"}.issubset(codes)

    pe = get_country_pack("pe")
    assert pe.currency == "PEN"
    assert pe.taxonomy_system == "NSE_APEIM"

    cl = get_country_pack("cl")
    assert cl.currency == "CLP"
    assert cl.taxonomy_system == "GSE_AIM"


def test_p6_report_agent_uses_v3_18_chapters_and_exports(tmp_path: Path, monkeypatch):
    from tests.test_v3_phase0 import _build_valid_bundle
    from app.services import report_agent_v2

    bundle, sctx = _build_valid_bundle()
    monkeypatch.setattr(
        report_agent_v2.ReportAgentV2,
        "_ensure_analytics_bundle",
        lambda self, sim_id: bundle,
    )

    agent = ReportAgent(
        graph_id="graph_p6_test",
        simulation_id="sim_p0_valid",
        simulation_requirement="Validar COFRE en Colombia",
    )
    report = agent.generate_report(report_id="rep_p6_e2e", use_v2=True)
    assert report.outline is not None
    assert len(report.outline.sections) == 18
    assert "Capítulo 00." in report.outline.sections[0].title
    assert "Capítulo 17." in report.outline.sections[-1].title

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    for fmt in ("md", "pdf", "pptx", "xlsx", "zip"):
        resp = client.get(f"/api/report/rep_p6_e2e/download?format={fmt}")
        assert resp.status_code == 200
        assert len(resp.data) > 100
