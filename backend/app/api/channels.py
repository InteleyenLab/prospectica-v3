"""Endpoints REST para simulación multicanal (/api/channels/*) y encuestas estructuradas (/api/swarm/*)."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from ..channels import adapters as _loaded_adapters  # noqa: F401
from ..channels.base import CANONICAL_CHANNEL_IDS, ChannelRegistry
from ..channels.engine import ChannelSimulationEngine
from ..channels.persistence import ChannelSQLiteStore
from ..config import Config
from ..models.project import ProjectManager
from ..models.task import TaskManager, TaskStatus
from ..services.simulation_manager import SimulationManager
from ..services.study_context_builder import (
    clean_study_topic,
    ensure_study_context,
    load_study_context,
)
from ..services.survey_engine import SurveyEngine
from ..utils.logger import get_logger

logger = get_logger("prospectica.api.channels")

channels_bp = Blueprint("channels", __name__)
swarm_bp = Blueprint("swarm", __name__)

_SURVEY_CANCEL_FLAGS: Dict[str, threading.Event] = {}


def _resolve_sim_dir(sim_id: str) -> Path:
    return Path(Config.OASIS_SIMULATION_DATA_DIR) / sim_id


def _clean_study_topic(requirement: str, project_name: str = "") -> str:
    """Extrae un tema limpio y legible unificado mediante `study_context_builder`."""
    return clean_study_topic(requirement=requirement, project_name=project_name)


def _load_country_and_targets(sim_id: str) -> Dict[str, Any]:
    state = SimulationManager().get_simulation(sim_id)
    if not state:
        return {
            "country_code": "co",
            "target_cities": None,
            "target_strata": None,
            "requirement": "",
            "project_name": "",
            "project_id": "",
            "study_context": None,
        }
    proj = ProjectManager.get_project(state.project_id) if state.project_id else None
    study_ctx = None
    if state.project_id:
        try:
            study_ctx = ensure_study_context(state.project_id) if proj else load_study_context(state.project_id)
        except Exception:
            study_ctx = None
    resolved_name = (
        (study_ctx or {}).get("project_name")
        or (getattr(proj, "name", "") if proj else "")
        or ""
    )
    return {
        "country_code": getattr(proj, "country_code", "co") if proj else "co",
        "target_cities": getattr(proj, "target_cities", None) if proj else None,
        "target_strata": getattr(proj, "target_strata", None) if proj else None,
        "requirement": (proj.simulation_requirement or "") if proj else "",
        "project_name": resolved_name,
        "project_id": state.project_id or "",
        "study_context": study_ctx,
    }


@channels_bp.route("/catalog", methods=["GET"])
def get_channels_catalog():
    """Retorna el catálogo oficial de los 11 canales colombianos + compatibilidad legada."""
    include_legacy = request.args.get("include_legacy", "true").lower() == "true"
    catalog = ChannelRegistry.list_catalog(include_legacy=include_legacy)
    return jsonify({"success": True, "data": catalog, "count": len(catalog)})


@channels_bp.route("/<sim_id>/events", methods=["GET"])
def get_channel_events(sim_id: str):
    """Lista eventos multicanal desde `simulation_channels.db` o fallback legado."""
    sim_dir = _resolve_sim_dir(sim_id)
    if not sim_dir.exists():
        return jsonify({"success": False, "error": f"Simulación no encontrada: {sim_id}"}), 404

    channel_id = request.args.get("channel_id") or None
    round_raw = request.args.get("round")
    round_num = int(round_raw) if round_raw and round_raw.isdigit() else None
    limit = min(500, max(1, int(request.args.get("limit", 100))))
    offset = max(0, int(request.args.get("offset", 0)))

    store = ChannelSQLiteStore(sim_dir)
    events = store.query_events(
        channel_id=channel_id,
        round_num=round_num,
        limit=limit,
        offset=offset,
        simulation_id=sim_id,
    )
    summary = store.summarize_channels(simulation_id=sim_id)
    return jsonify(
        {
            "success": True,
            "data": {
                "simulation_id": sim_id,
                "count": len(events),
                "events": events,
                "channels_summary": summary,
            },
        }
    )


@channels_bp.route("/<sim_id>/sessions/<channel_id>", methods=["GET"])
def get_channel_sessions(sim_id: str, channel_id: str):
    """Retorna sesiones o registros detallados de un canal (WhatsApp, Focus Group, Encuestas, Medios)."""
    sim_dir = _resolve_sim_dir(sim_id)
    if not sim_dir.exists():
        return jsonify({"success": False, "error": f"Simulación no encontrada: {sim_id}"}), 404

    limit = min(500, max(1, int(request.args.get("limit", 200))))
    store = ChannelSQLiteStore(sim_dir)
    payload = store.query_sessions(channel_id=channel_id, limit=limit, simulation_id=sim_id)
    return jsonify({"success": True, "data": payload})


@channels_bp.route("/<sim_id>/run", methods=["POST"])
def run_multichannel_simulation(sim_id: str):
    """Ejecuta rondas multicanal sobre los canales habilitados y persiste las 5 tablas WAL."""
    sim_dir = _resolve_sim_dir(sim_id)
    sim_dir.mkdir(parents=True, exist_ok=True)
    body = request.get_json(silent=True) or {}

    state = SimulationManager().get_simulation(sim_id)
    default_channels = getattr(state, "enabled_channels", None) or CANONICAL_CHANNEL_IDS
    enabled_channels: List[str] = body.get("enabled_channels") or default_channels
    rounds = max(1, min(12, int(body.get("rounds", 2))))
    ctx_info = _load_country_and_targets(sim_id)

    if not body.get("append", False):
        ChannelSQLiteStore(sim_dir).clear_simulation_channel_data(sim_id)

    merged_study_context = dict(ctx_info.get("study_context") or {})
    merged_study_context["topic_short"] = _clean_study_topic(
        ctx_info["requirement"],
        ctx_info.get("project_name", ""),
    )

    engine = ChannelSimulationEngine(
        simulation_id=sim_id,
        sim_dir=sim_dir,
        country_code=ctx_info["country_code"],
    )
    summary = engine.run_rounds(
        enabled_channels=enabled_channels,
        rounds=rounds,
        study_context=merged_study_context,
    )
    return jsonify({"success": True, "data": summary})


@swarm_bp.route("/<sim_id>/survey/run", methods=["POST"])
def run_structured_survey(sim_id: str):
    """Lanza encuesta estructurada estratificada (N=300+ por defecto) sin timeouts HTTP."""
    sim_dir = _resolve_sim_dir(sim_id)
    sim_dir.mkdir(parents=True, exist_ok=True)
    body = request.get_json(silent=True) or {}

    sample_size = max(1, min(2000, int(body.get("sample_size", 300))))
    use_llm = bool(body.get("use_llm", False))
    sync_mode = bool(body.get("sync", False))
    batch_size = max(1, min(25, int(body.get("batch_size", 10))))
    ctx_info = _load_country_and_targets(sim_id)
    study_ctx = ctx_info.get("study_context") or {}
    price_ladder = body.get("price_ladder") or study_ctx.get("price_ladder_cop")
    if body.get("study_topic"):
        topic = body["study_topic"]
    elif ctx_info["requirement"] or ctx_info.get("project_name"):
        topic = _clean_study_topic(ctx_info["requirement"], ctx_info.get("project_name", ""))
    else:
        topic = "Estudio de mercado en Colombia"
    append_mode = bool(body.get("append", False))

    task_mgr = TaskManager()
    task_id = task_mgr.create_task(
        task_type="structured_survey",
        metadata={"simulation_id": sim_id, "sample_size": sample_size, "use_llm": use_llm},
    )
    cancel_ev = threading.Event()
    _SURVEY_CANCEL_FLAGS[task_id] = cancel_ev

    def _execute() -> Dict[str, Any]:
        task_mgr.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            progress=5,
            message=f"Iniciando encuesta estructurada N={sample_size}...",
        )
        if not append_mode:
            ChannelSQLiteStore(sim_dir).clear_simulation_surveys(
                sim_id,
                channel_origin="structured_survey",
            )
        engine = SurveyEngine(country_code=ctx_info["country_code"])

        def _on_progress(done: int, total: int, msg: str) -> None:
            pct = min(99, max(5, int((done / max(1, total)) * 95)))
            task_mgr.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=pct,
                message=msg,
                progress_detail={"completed": done, "total": total},
            )

        result = engine.run_survey(
            simulation_id=sim_id,
            sim_dir=sim_dir,
            sample_size=sample_size,
            target_cities=ctx_info["target_cities"],
            target_strata=ctx_info["target_strata"],
            study_topic=topic,
            price_ladder=price_ladder,
            use_llm=use_llm,
            batch_size=batch_size,
            progress_callback=_on_progress,
            cancel_checker=cancel_ev.is_set,
        )
        task_mgr.complete_task(task_id, result=result)
        return result

    if sync_mode:
        try:
            res = _execute()
            return jsonify({"success": True, "data": {"task_id": task_id, "status": "completed", "result": res}})
        except Exception as exc:  # noqa: BLE001
            task_mgr.fail_task(task_id, str(exc))
            return jsonify({"success": False, "error": str(exc)}), 500

    def _bg_worker() -> None:
        try:
            _execute()
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Error en encuesta asíncrona {task_id}: {exc}")
            task_mgr.fail_task(task_id, str(exc))

    threading.Thread(target=_bg_worker, daemon=True).start()
    return (
        jsonify(
            {
                "success": True,
                "data": {
                    "simulation_id": sim_id,
                    "task_id": task_id,
                    "status": "processing",
                    "sample_size": sample_size,
                },
            }
        ),
        202,
    )


@swarm_bp.route("/<sim_id>/tasks/<task_id>", methods=["GET"])
def get_swarm_task_status(sim_id: str, task_id: str):
    """Consulta el estado de una tarea asíncrona de encuesta o enjambre."""
    task = TaskManager().get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": f"Tarea no encontrada: {task_id}"}), 404
    return jsonify({"success": True, "data": task.to_dict()})


@swarm_bp.route("/<sim_id>/tasks/<task_id>/cancel", methods=["POST"])
def cancel_swarm_task(sim_id: str, task_id: str):
    """Cancela cooperativamente una tarea activa."""
    ev = _SURVEY_CANCEL_FLAGS.get(task_id)
    if ev:
        ev.set()
    task = TaskManager().get_task(task_id)
    if not task:
        return jsonify({"success": False, "error": f"Tarea no encontrada: {task_id}"}), 404
    return jsonify({"success": True, "data": {"task_id": task_id, "cancel_requested": True}})


@swarm_bp.route("/<sim_id>/sessions", methods=["GET", "POST"])
def handle_swarm_sessions(sim_id: str):
    """Lista o crea/rehidrata una sesión persistente del enjambre Orkas sin requerir OASIS vivo."""
    from ..swarm import SwarmOrchestrator, SwarmTranscript

    sim_dir = _resolve_sim_dir(sim_id)
    sim_dir.mkdir(parents=True, exist_ok=True)
    if request.method == "GET":
        sessions = SwarmTranscript(sim_dir).list_sessions()
        return jsonify({"success": True, "data": {"simulation_id": sim_id, "sessions": sessions}})

    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id")
    use_llm = bool(body.get("use_llm", False))
    orch = SwarmOrchestrator(simulation_id=sim_id, sim_dir=sim_dir, use_llm=use_llm)
    payload = orch.create_or_get_session(session_id=session_id)
    return jsonify({"success": True, "data": payload})


@swarm_bp.route("/<sim_id>/message", methods=["POST"])
def post_swarm_message(sim_id: str):
    """Envía un mensaje humano al enjambre Orkas (soporta @menciones, handoff y rehidratación)."""
    from ..swarm import SwarmOrchestrator

    sim_dir = _resolve_sim_dir(sim_id)
    sim_dir.mkdir(parents=True, exist_ok=True)
    body = request.get_json(silent=True) or {}
    session_id = body.get("session_id")
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"success": False, "error": "El campo 'message' es obligatorio"}), 400

    use_llm = bool(body.get("use_llm", False))
    orch = SwarmOrchestrator(simulation_id=sim_id, sim_dir=sim_dir, use_llm=use_llm)
    if not session_id:
        session_id = orch.create_or_get_session()["session"]["session_id"]
    result = orch.send_message(session_id=session_id, text=message)
    return jsonify({"success": True, "data": result})

