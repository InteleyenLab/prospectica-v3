"""Endpoints REST V3 (Fase 0..3): Brief, Confirmación StudyContext, Investigación Secundaria y Validadores."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from flask import Blueprint, jsonify, request

from ..config import Config
from ..models.project import ProjectManager
from ..services.analytics.bundle_builder import AnalyticsBundleBuilder
from ..services.backtesting import DEFAULT_BACKTEST_CASES, BacktestingEngine
from ..services.calibration import BayesianCalibrator, CalibrationEngine
from ..services.compliance import (
    EXCLUDED_CATEGORY_PATTERNS,
    record_consent,
    scan_pii,
)
from ..services.github_connector import GitHubReadOnlyConnector
from ..services.persona_engine_v2 import PersonaEngineV2
from ..services.report_builder_v3 import ReportBuilderV3
from ..services.secondary_research import SecondaryResearchEngine
from ..services.simulation_manager import SimulationManager
from ..services.study_context_builder import (
    confirm_study_context,
    ensure_study_context,
    extract_and_build_study_context,
    load_study_context,
)
from ..services.validators import ReportValidator

v3_bp = Blueprint("v3", __name__)


def _resolve_project_dir(project_id: str) -> Path:
    return Path(ProjectManager._get_project_dir(project_id))


@v3_bp.route("/brief", methods=["POST"])
def submit_brief():
    """Registra el Intake Brief (Anexo A) + consentimientos y actualiza StudyContext."""
    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"success": False, "error": "project_id es obligatorio"}), 400

    proj_dir = _resolve_project_dir(project_id)
    proj_dir.mkdir(parents=True, exist_ok=True)

    brief = data.get("brief") if isinstance(data.get("brief"), dict) else data
    brief_text = json.dumps(brief, ensure_ascii=False)
    for _cat, _desc, pat in EXCLUDED_CATEGORY_PATTERNS:
        if pat.search(brief_text):
            return (
                jsonify(
                    {
                        "success": False,
                        "error": f"Categoría excluida por política de cumplimiento (V-42): {_desc}",
                        "code": "V-42",
                    }
                ),
                400,
            )

    pii_hits = scan_pii(brief_text)
    consent_raw = data.get("consent") if isinstance(data.get("consent"), dict) else {}
    consent_record = record_consent(
        project_id=project_id,
        accepted_privacy=bool(consent_raw.get("accepted_privacy", True)),
        accepted_synthetic_nature=bool(consent_raw.get("accepted_synthetic_nature", True)),
        no_unnecessary_pii=bool(consent_raw.get("no_unnecessary_pii", True)),
        actor_name=str(data.get("actor_name") or "cliente"),
        project_dir=proj_dir,
    )

    brief_payload = {
        "project_id": project_id,
        "brief": brief,
        "pii_detected": pii_hits,
        "consent": consent_record,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    (proj_dir / "brief.json").write_text(
        json.dumps(brief_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    proj = ProjectManager.get_project(project_id)
    extracted = getattr(proj, "extracted_text", "") if proj else str(brief.get("description") or "")
    req = getattr(proj, "simulation_requirement", "") if proj else str(brief.get("objective") or "")
    pname = str(brief.get("project_name") or (getattr(proj, "name", "") if proj else ""))
    sctx = extract_and_build_study_context(
        project_id=project_id,
        project_name_hint=pname,
        extracted_text=extracted,
        simulation_requirement=req,
        use_llm=False,
        project_dir=proj_dir,
        save=True,
    )

    return jsonify(
        {
            "success": True,
            "data": {
                "project_id": project_id,
                "brief": brief_payload,
                "study_context": sctx,
            },
        }
    )


@v3_bp.route("/study-context/confirm", methods=["POST"])
def confirm_project_study_context():
    """Confirma explícitamente StudyContext y BusinessModelTemplate (Paso 1 bloqueante)."""
    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"success": False, "error": "project_id es obligatorio"}), 400

    proj_dir = _resolve_project_dir(project_id)
    updates = data.get("updates") if isinstance(data.get("updates"), dict) else None
    confirmed_by = str(data.get("confirmed_by") or "cliente")

    sctx = confirm_study_context(
        project_id=project_id,
        updates=updates,
        confirmed_by=confirmed_by,
        project_dir=proj_dir,
    )
    if not sctx:
        return jsonify({"success": False, "error": "StudyContext no encontrado para este proyecto"}), 404

    return jsonify({"success": True, "data": sctx})


@v3_bp.route("/research/secondary/run", methods=["POST"])
def run_secondary_research():
    """Ejecuta el módulo de Investigación Secundaria (TAM/SAM/SOM, Competidores y Evidence Ledger)."""
    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"success": False, "error": "project_id es obligatorio"}), 400

    proj_dir = _resolve_project_dir(project_id)
    sctx = load_study_context(project_id, project_dir=proj_dir)
    if not sctx:
        sctx = extract_and_build_study_context(
            project_id=project_id,
            project_name_hint=str(data.get("project_name") or ""),
            extracted_text=str(data.get("extracted_text") or ""),
            simulation_requirement=str(data.get("simulation_requirement") or ""),
            use_llm=False,
            project_dir=proj_dir,
            save=True,
        )

    result = SecondaryResearchEngine().run(
        study_context=sctx,
        quant_indicators=data.get("quant_indicators"),
        project_dir=proj_dir,
    )
    return jsonify({"success": True, "data": result})


@v3_bp.route("/research/evidence", methods=["GET"])
def get_research_evidence():
    """Retorna el Evidence Ledger persistido de un proyecto."""
    project_id = str(request.args.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"success": False, "error": "project_id es obligatorio"}), 400

    ledger_path = _resolve_project_dir(project_id) / "evidence_ledger.json"
    if not ledger_path.exists():
        return jsonify({"success": True, "data": {"items": [], "count": 0}})

    items = json.loads(ledger_path.read_text(encoding="utf-8"))
    return jsonify({"success": True, "data": {"items": items, "count": len(items)}})


@v3_bp.route("/validators/run", methods=["POST"])
def run_validators():
    """Ejecuta las 45 reglas de consistencia V-01..V-45 sobre un bundle o simulación."""
    data = request.get_json(silent=True) or {}
    bundle = data.get("bundle")
    study_ctx = data.get("study_context")
    simulation_id = str(data.get("simulation_id") or "").strip()

    if not bundle and simulation_id:
        sim_dir = Path(Config.UPLOAD_FOLDER) / "simulations" / simulation_id
        bundle_path = sim_dir / "analytics_bundle.json"
        if bundle_path.exists():
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        else:
            st = SimulationManager().get_simulation(simulation_id)
            proj_dir = _resolve_project_dir(st.project_id) if (st and st.project_id) else None
            bundle = AnalyticsBundleBuilder().build(
                simulation_id=simulation_id,
                sim_dir=sim_dir,
                project_dir=proj_dir,
                write_file=False,
            )
        if not study_ctx:
            st = SimulationManager().get_simulation(simulation_id)
            if st and st.project_id:
                study_ctx = load_study_context(st.project_id)

    if not isinstance(bundle, dict):
        return jsonify({"success": False, "error": "Se requiere bundle o simulation_id válido"}), 400

    res = ReportValidator().validate(
        bundle=bundle,
        study_context=study_ctx,
        report_markdown=str(data.get("report_markdown") or ""),
        analyst_signature=data.get("analyst_signature"),
        calibration_result=data.get("calibration_result"),
        real_data_batch=data.get("real_data_batch"),
        transparency_sheet_complete=bool(data.get("transparency_sheet_complete", True)),
    )
    return jsonify({"success": True, "data": res})


@v3_bp.route("/validators/report", methods=["GET"])
def get_validator_report():
    """Obtiene el validation_report.json generado junto al informe."""
    report_id = str(request.args.get("report_id") or "").strip()
    if not report_id:
        return jsonify({"success": False, "error": "report_id es obligatorio"}), 400

    val_path = Path(Config.UPLOAD_FOLDER) / "reports" / report_id / "validation_report.json"
    if not val_path.exists():
        return jsonify({"success": False, "error": "validation_report.json no encontrado"}), 404

    payload = json.loads(val_path.read_text(encoding="utf-8"))
    return jsonify({"success": True, "data": payload})


@v3_bp.route("/personas/v2/generate", methods=["POST"])
def generate_personas_v2():
    """Genera cohorte de personas sintéticas V2 (7 capas + controles de diversidad)."""
    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    count = int(data.get("count") or 30)
    seed = int(data.get("seed") or 2026)
    sctx = load_study_context(project_id) if project_id else (data.get("study_context") or {})
    res = PersonaEngineV2(country_code=str(data.get("country_code") or "co")).generate_cohort(
        count=count,
        study_context=sctx,
        seed=seed,
    )
    return jsonify({"success": True, "data": res})


@v3_bp.route("/calibration/run", methods=["POST"])
def run_calibration_gate():
    """Ejecuta el Gate de Calibración contra el Banco de Anclas Colombia."""
    data = request.get_json(silent=True) or {}
    bundle = data.get("bundle") or {}
    project_id = str(data.get("project_id") or "").strip()
    sctx = data.get("study_context") or (load_study_context(project_id) if project_id else {})
    res = CalibrationEngine().evaluate_gate(bundle=bundle, study_context=sctx)
    return jsonify({"success": True, "data": res})


@v3_bp.route("/real-data/upload", methods=["POST"])
@v3_bp.route("/calibration/update", methods=["POST"])
def upload_real_data_and_recalibrate():
    """Recibe datos reales (piloto/encuesta) y ejecuta recalibración bayesiana Beta-Binomial."""
    data = request.get_json(silent=True) or {}
    project_id = str(data.get("project_id") or "").strip()
    if not project_id:
        return jsonify({"success": False, "error": "project_id es obligatorio"}), 400

    proj_dir = _resolve_project_dir(project_id)
    res = BayesianCalibrator.update_with_real_data(
        prior_conversion_rate=float(data.get("prior_conversion_rate") or 0.08),
        real_trials=int(data.get("real_trials") or 0),
        real_conversions=int(data.get("real_conversions") or 0),
        prior_strength=float(data.get("prior_strength") or 20.0),
        project_dir=proj_dir,
        notes=str(data.get("notes") or ""),
    )
    return jsonify({"success": True, "data": res})


@v3_bp.route("/v3/report/generate", methods=["POST"])
def generate_v3_report():
    """Genera el informe V3 de 18 capítulos con semáforo de confianza y validación V-01..V-45."""
    data = request.get_json(silent=True) or {}
    report_id = str(data.get("report_id") or "").strip()
    simulation_id = str(data.get("simulation_id") or "").strip()
    if not report_id or not simulation_id:
        return jsonify({"success": False, "error": "report_id y simulation_id son obligatorios"}), 400

    bundle = data.get("bundle")
    if not bundle:
        sim_dir = Path(Config.UPLOAD_FOLDER) / "simulations" / simulation_id
        bpath = sim_dir / "analytics_bundle.json"
        bundle = json.loads(bpath.read_text(encoding="utf-8")) if bpath.exists() else {}

    sctx = data.get("study_context")
    if not sctx:
        st = SimulationManager().get_simulation(simulation_id)
        if st and st.project_id:
            sctx = load_study_context(st.project_id)

    res = ReportBuilderV3().build_report(
        report_id=report_id,
        simulation_id=simulation_id,
        bundle=bundle,
        study_context=sctx,
        analyst_signature=str(data.get("analyst_signature") or "Analista Principal Prospéctica"),
    )
    return jsonify({"success": True, "data": res})


@v3_bp.route("/backtesting/run", methods=["POST"])
def run_backtesting():
    """Ejecuta el suite de backtesting histórico contra casos reales."""
    data = request.get_json(silent=True) or {}
    cases = data.get("cases") or DEFAULT_BACKTEST_CASES
    res = BacktestingEngine.run_benchmark_suite(cases)
    return jsonify({"success": True, "data": res})


@v3_bp.route("/backtesting/dashboard", methods=["GET"])
def get_backtesting_dashboard():
    """Retorna el tablero de desempeño histórico con los 15 casos de referencia Colombia."""
    res = BacktestingEngine.run_benchmark_suite(DEFAULT_BACKTEST_CASES)
    return jsonify({"success": True, "data": res})


@v3_bp.route("/connectors/github/inspect", methods=["POST"])
def inspect_github_readonly():
    """Inspecciona un repositorio GitHub en modo solo lectura con escaneo de secretos."""
    data = request.get_json(silent=True) or {}
    repo_url = str(data.get("repo_url") or "").strip()
    if not repo_url:
        return jsonify({"success": False, "error": "repo_url es obligatorio"}), 400
    res = GitHubReadOnlyConnector.analyze_repository_snapshot(
        repo_url=repo_url,
        readme_text=str(data.get("readme_text") or ""),
        file_tree=data.get("file_tree"),
        package_files=data.get("package_files"),
    )
    return jsonify({"success": True, "data": res})


@v3_bp.route("/compliance/records", methods=["GET"])
def get_compliance_records():
    """Lista registros de consentimiento y cumplimiento de proyectos."""
    project_id = str(request.args.get("project_id") or "").strip()
    records = []
    if project_id:
        cpath = _resolve_project_dir(project_id) / "compliance_consent.json"
        if cpath.exists():
            records.append(json.loads(cpath.read_text(encoding="utf-8")))
    return jsonify({"success": True, "data": {"records": records, "count": len(records)}})


@v3_bp.route("/project/<project_id>/data", methods=["DELETE"])
def delete_project_data_compliance(project_id: str):
    """Elimina datos del proyecto bajo demanda (Ley 1581 Habeas Data)."""
    import shutil

    pdir = _resolve_project_dir(project_id)
    existed = pdir.exists()
    if existed:
        shutil.rmtree(pdir, ignore_errors=True)
    return jsonify(
        {
            "success": True,
            "data": {
                "project_id": project_id,
                "deleted": existed,
                "deleted_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    )
