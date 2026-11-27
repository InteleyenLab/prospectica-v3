"""Pruebas unitarias e integración de Fase 2 (Informe 18 Capítulos V3, Exportadores PDF/PPTX/XLSX/ZIP y Backtesting)."""

from __future__ import annotations

import zipfile
from pathlib import Path

from app import create_app
from app.services.backtesting import BacktestingEngine
from app.services.report_builder_v3 import CHAPTER_SPECS_V3, ReportBuilderV3
from app.services.report_exporters import export_pdf, export_pptx, export_xlsx, export_zip
from tests.test_v3_phase0 import _build_valid_bundle


def test_p2_report_builder_v3_18_chapters_and_validation(tmp_path: Path):
    bundle, sctx = _build_valid_bundle()
    res = ReportBuilderV3().build_report(
        report_id="rep_p2_v3",
        simulation_id="sim_p0_valid",
        bundle=bundle,
        study_context=sctx,
        analyst_signature="Dra. Camila Restrepo",
        output_dir=tmp_path,
    )
    assert len(CHAPTER_SPECS_V3) == 18
    assert len(res["chapters"]) == 18
    assert res["manifest"]["version"] == "v3_18ch"
    assert res["confidence_grade"]["grade"] in ("A", "B", "C", "D")
    assert res["validation_report"]["status"] == "PASS"
    assert (tmp_path / "full_report.md").exists()
    assert (tmp_path / "validation_report.json").exists()
    assert (tmp_path / "report_manifest.json").exists()


def test_p2_exporters_pdf_pptx_xlsx_zip(tmp_path: Path):
    bundle, sctx = _build_valid_bundle()
    res = ReportBuilderV3().build_report(
        report_id="rep_p2_exp",
        simulation_id="sim_p0_valid",
        bundle=bundle,
        study_context=sctx,
        output_dir=tmp_path,
    )
    manifest = res["manifest"]
    full_md = res["markdown_content"]
    chapters = res["chapters"]

    pdf_p = export_pdf(tmp_path, manifest, full_md)
    pptx_p = export_pptx(tmp_path, manifest, chapters)
    xlsx_p = export_xlsx(tmp_path, manifest, bundle)
    zip_p = export_zip(tmp_path, manifest, full_md, bundle, chapters)

    assert pdf_p.exists() and pdf_p.stat().st_size > 500
    assert pptx_p.exists() and pptx_p.stat().st_size > 500
    assert xlsx_p.exists() and xlsx_p.stat().st_size > 500
    assert zip_p.exists()
    with zipfile.ZipFile(zip_p, "r") as zf:
        names = zf.namelist()
        assert "full_report.md" in names
        assert "analytics_bundle.json" in names
        assert "validation_report.json" in names


def test_p2_backtesting_engine_and_api():
    suite = BacktestingEngine.run_benchmark_suite(
        [
            {
                "case_name": "Caso Fintech CO 2024",
                "predicted_conversion": 0.12,
                "actual_conversion": 0.10,
                "predicted_price_cop": 50000,
                "actual_price_cop": 48000,
                "predicted_go": True,
                "actual_success": True,
            },
            {
                "case_name": "Caso EdTech CO 2024",
                "predicted_conversion": 0.05,
                "actual_conversion": 0.04,
                "predicted_price_cop": 90000,
                "actual_price_cop": 100000,
                "predicted_go": False,
                "actual_success": False,
            },
        ]
    )
    assert suite["cases_count"] == 2
    assert suite["decision_accuracy_pct"] == 100.0
    assert suite["mean_conversion_mae_pp"] == 1.5

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()
    r = client.post(
        "/api/backtesting/run",
        json={
            "cases": [
                {
                    "case_name": "Caso Test",
                    "predicted_conversion": 0.1,
                    "actual_conversion": 0.1,
                    "predicted_price_cop": 50000,
                    "actual_price_cop": 50000,
                    "predicted_go": True,
                    "actual_success": True,
                }
            ]
        },
    )
    assert r.status_code == 200
    assert r.get_json()["data"]["decision_accuracy_pct"] == 100.0
