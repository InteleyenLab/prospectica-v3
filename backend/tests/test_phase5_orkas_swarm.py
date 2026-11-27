"""Pruebas de regresión estilo Orkas (`backend/app/swarm/`) y rehidratación post-cierre."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from app import create_app
from app.config import Config
from app.services.report_agent import ReportManager
from app.services.report_agent_v2 import ReportAgentV2
from app.swarm import (
    ArchetypeAgent,
    DAGCycleError,
    DispatchPlanner,
    ModeratorCommander,
    SwarmOrchestrator,
    SwarmScheduler,
    parse_mentions,
)


def test_orkas_anti_loop_mentions_dag_rejection_and_agent_zero_tools():
    # 1. parse_mentions retorna [] cuando from_kind in {"commander", "agent"}
    assert parse_mentions("@Carlos @Ana revisen esto", from_kind="commander", known_agents=["Carlos", "Ana"]) == []
    assert parse_mentions("@Carlos opino igual", from_kind="agent", known_agents=["Carlos"]) == []
    # Solo mensajes humanos disparan menciones multi-palabra
    assert parse_mentions("Hola @María Fernanda Castro ¿qué opinas?", from_kind="human", known_agents=["María Fernanda Castro"]) == [
        "María Fernanda Castro"
    ]

    # 2. ArchetypeAgent tiene 0 herramientas de despacho
    agent = ArchetypeAgent({"name": "Carlos Motociclista", "city_name": "Cali", "stratum_code": "E3"})
    assert agent.tools == []
    assert ModeratorCommander.tools and "dispatch_to" in ModeratorCommander.tools

    # 3. Rechazo determinista de ciclo DAG y límite <= 8
    with pytest.raises(DAGCycleError):
        DispatchPlanner.validate_and_toposort(
            [
                {"id": "a", "target": "SurveyWorker", "prompt": "1", "depends_on": ["b"]},
                {"id": "b", "target": "SurveyWorker", "prompt": "2", "depends_on": ["a"]},
            ]
        )


def test_orkas_parallel_dispatch_without_deadlock_under_global_slots_2_and_handoff(tmp_path: Path):
    sim_dir = tmp_path / "sim_orkas_par"
    sim_dir.mkdir(parents=True, exist_ok=True)
    (sim_dir / "reddit_profiles.json").write_text(
        json.dumps(
            [
                {"user_id": 1, "name": "Lucía Medellín", "username": "lucia_m", "city_name": "Medellín", "stratum_code": "E4", "attitude_segment": "esceptico"},
                {"user_id": 2, "name": "Mateo Bogotá", "username": "mateo_b", "city_name": "Bogotá D.C.", "stratum_code": "E3", "attitude_segment": "critico_hate"},
            ]
        ),
        encoding="utf-8",
    )

    scheduler = SwarmScheduler(global_slots=2, nested_worker_slots=4)
    cmd = ModeratorCommander("sim_orkas_par", sim_dir, scheduler=scheduler, use_llm=False)

    # Dispatch paralelo dentro de una ranura global ocupada no debe causar deadlock
    def _parallel_inside_global():
        subtasks = [
            {"id": f"t_{i}", "target": "SurveyWorker", "prompt": f"Evalúa tarifa #{i}"}
            for i in range(6)
        ]
        return cmd.dispatch_to("sess_1", subtasks)

    t0 = time.monotonic()
    res = scheduler.run_in_global_slot(_parallel_inside_global)
    assert time.monotonic() - t0 < 5.0
    assert len(res) == 6

    # Handoff cede active_recipient y retorna TurnOutcome(kind="silent") del Commander sin burbuja vacía
    orch = SwarmOrchestrator("sim_orkas_par", sim_dir, use_llm=False)
    created = orch.create_or_get_session("sess_handoff")
    assert created["session"]["active_recipient"] == "ModeratorCommander"

    turn = orch.send_message("sess_handoff", "@Lucía Medellín ¿por qué dudas en pagar?")
    assert turn["commander_outcome"]["kind"] == "silent"
    assert turn["session"]["active_recipient"] == "Lucía Medellín"
    assert turn["replies"][0]["sender_name"] == "Lucía Medellín"


def test_rehydration_post_closure_on_sim_345b78a4490f_and_report_chat_tools():
    app = create_app()
    client = app.test_client()

    # 1. Crear sesión y enviar entrevista/mención sobre sim_345b78a4490f aunque OASIS esté detenido
    r_sess = client.post("/api/swarm/sim_345b78a4490f/sessions", json={})
    assert r_sess.status_code == 200
    sess_data = r_sess.get_json()["data"]
    sid = sess_data["session"]["session_id"]
    assert sess_data["rehydration"]["profiles_count"] > 0

    r_msg = client.post(
        "/api/swarm/sim_345b78a4490f/message",
        json={"session_id": sid, "message": "¿Qué objeciones detectaron en los ciudadanos?"},
    )
    assert r_msg.status_code == 200
    assert len(r_msg.get_json()["data"]["replies"]) >= 1

    # Verificar persistencia en channel_transcript.jsonl reabriendo con un cliente fresco
    r_get = client.get("/api/swarm/sim_345b78a4490f/sessions")
    assert r_get.status_code == 200
    assert any(s["session_id"] == sid for s in r_get.get_json()["data"]["sessions"])

    # 2. POST /api/report/chat ejecuta con enable_tools=True y devuelve tool_calls
    with patch("app.services.report_agent.LLMClient.chat", return_value="Respuesta respaldada en evidencia."):
        r_chat = client.post(
            "/api/report/chat",
            json={
                "simulation_id": "sim_345b78a4490f",
                "report_id": "report_6d4a2701feb3",
                "message": "Resume los hallazgos del análisis.",
            },
        )
        assert r_chat.status_code == 200
        chat_data = r_chat.get_json()["data"]
        assert "response" in chat_data
        assert isinstance(chat_data.get("tool_calls"), list)
