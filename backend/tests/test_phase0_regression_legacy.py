"""Pruebas de Fase 0: Regresión histórica (NEXO) y persistencia SQLite en system_tasks."""

import sqlite3
from pathlib import Path

from app import create_app
from app.models.task import TaskManager, TaskStatus


def test_historical_nexo_endpoints_return_200():
    app = create_app()
    client = app.test_client()

    for url in (
        "/api/graph/project/proj_047fbadfa161",
        "/api/simulation/sim_345b78a4490f",
        "/api/simulation/history",
        "/api/report/report_6d4a2701feb3",
    ):
        resp = client.get(url)
        assert resp.status_code == 200, f"Fallo en {url}: {resp.status_code} {resp.get_data(as_text=True)}"
        payload = resp.get_json()
        assert payload and payload.get("success") is True


def test_task_manager_persists_in_sqlite_across_singleton_restart(tmp_path):
    db_file = tmp_path / "system_tasks.db"
    prev_instance = TaskManager._instance
    TaskManager._instance = None
    try:
        tm1 = TaskManager(db_path=str(db_file))
        task_id = tm1.create_task("phase0_test", metadata={"proyecto": "nexo"})
        tm1.update_task(
            task_id,
            status=TaskStatus.PROCESSING,
            progress=55,
            message="Procesando prueba",
        )

        with sqlite3.connect(str(db_file)) as conn:
            row = conn.execute(
                "SELECT status, progress, message FROM system_tasks WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        assert row == ("processing", 55, "Procesando prueba")

        # Simular reinicio del singleton Flask
        TaskManager._instance = None
        tm2 = TaskManager(db_path=str(db_file))
        recovered = tm2.get_task(task_id)
        assert recovered is not None
        assert recovered.status == TaskStatus.PROCESSING
        assert recovered.progress == 55
        assert recovered.metadata == {"proyecto": "nexo"}
    finally:
        TaskManager._instance = prev_instance
