"""Endpoints REST para el pipeline determinístico `/api/analytics/<sim_id>/run` y `/bundle`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from flask import Blueprint, jsonify, request

from ..config import Config
from ..models.project import ProjectManager
from ..services.analytics import AnalyticsBundleBuilder
from ..services.simulation_manager import SimulationManager

analytics_bp = Blueprint("analytics", __name__)


def _resolve_sim_and_project(sim_id: str) -> tuple[Path, Optional[Path], str]:
    sim_dir = Path(Config.OASIS_SIMULATION_DATA_DIR) / sim_id
    state = SimulationManager().get_simulation(sim_id)
    project_dir: Optional[Path] = None
    country_code = "co"
    if state and state.project_id:
        project_dir = Path(ProjectManager._get_project_dir(state.project_id))
        proj = ProjectManager.get_project(state.project_id)
        if proj and getattr(proj, "country_code", None):
            country_code = proj.country_code
    return sim_dir, project_dir, country_code


@analytics_bp.route("/<sim_id>/run", methods=["POST"])
def run_analytics_pipeline(sim_id: str):
    """Ejecuta el pipeline determinístico completo y persiste `analytics_bundle.json`."""
    sim_dir, project_dir, country_code = _resolve_sim_and_project(sim_id)
    if not sim_dir.exists():
        return jsonify({"success": False, "error": f"Simulación no encontrada: {sim_id}"}), 404

    bundle = AnalyticsBundleBuilder().build(
        simulation_id=sim_id,
        sim_dir=sim_dir,
        project_dir=project_dir,
        country_code=country_code,
        write_file=True,
    )
    return jsonify(
        {
            "success": True,
            "data": {
                "simulation_id": sim_id,
                "sha256_hash": bundle["sha256_hash"],
                "data_audit": bundle["data_audit"],
                "warnings": bundle["warnings"],
                "bundle_path": str(sim_dir / "analytics_bundle.json"),
            },
        }
    )


@analytics_bp.route("/<sim_id>/bundle", methods=["GET"])
def get_analytics_bundle(sim_id: str):
    """Retorna `analytics_bundle.json` completo o el slice de un capítulo con `?chapter=<01..12>`."""
    sim_dir, project_dir, country_code = _resolve_sim_and_project(sim_id)
    if not sim_dir.exists():
        return jsonify({"success": False, "error": f"Simulación no encontrada: {sim_id}"}), 404

    bundle_path = sim_dir / "analytics_bundle.json"
    db_path = sim_dir / "simulation_channels.db"
    if not sim_dir.exists() or (not bundle_path.exists() and not db_path.exists()):
        return jsonify({"success": False, "error": f"Simulación no encontrada: {sim_id}"}), 404

    is_stale = not bundle_path.exists()
    if not is_stale and db_path.exists():
        try:
            if db_path.stat().st_mtime > bundle_path.stat().st_mtime:
                is_stale = True
        except OSError:
            is_stale = True

    if not is_stale:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    else:
        bundle = AnalyticsBundleBuilder().build(
            simulation_id=sim_id,
            sim_dir=sim_dir,
            project_dir=project_dir,
            country_code=country_code,
            write_file=True,
        )

    chapter = request.args.get("chapter")
    if chapter:
        ch_key = chapter.zfill(2) if chapter.isdigit() else chapter
        slice_data = (bundle.get("chapter_slices") or {}).get(ch_key)
        if slice_data is None:
            return jsonify({"success": False, "error": f"Capítulo no encontrado: {chapter}"}), 404
        return jsonify(
            {
                "success": True,
                "data": {
                    "simulation_id": sim_id,
                    "chapter": ch_key,
                    "sha256_hash": bundle.get("sha256_hash"),
                    "slice": slice_data,
                },
            }
        )

    return jsonify({"success": True, "data": bundle})
