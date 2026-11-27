"""Tablero de tareas del enjambre persistido en SQLite WAL (`swarm_tasks`)."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class TaskBoard:
    """Gestiona subtareas de despacho en `<sim_dir>/swarm_memory/swarm_tasks.db`."""

    SCHEMA_SQL = """
    PRAGMA journal_mode=WAL;
    CREATE TABLE IF NOT EXISTS swarm_tasks (
        task_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        target_actor TEXT NOT NULL,
        prompt TEXT NOT NULL,
        status TEXT NOT NULL,
        result_text TEXT,
        error TEXT,
        metadata_json TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """

    def __init__(self, swarm_dir: Path):
        self.swarm_dir = Path(swarm_dir)
        self.swarm_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.swarm_dir / "swarm_tasks.db"
        with self._connect() as conn:
            conn.executescript(self.SCHEMA_SQL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=20.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def upsert_task(
        self,
        task_id: str,
        session_id: str,
        target_actor: str,
        prompt: str,
        status: str = "pending",
        result_text: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO swarm_tasks (
                    task_id, session_id, target_actor, prompt, status,
                    result_text, error, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    result_text=excluded.result_text,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (
                    task_id,
                    session_id,
                    target_actor,
                    prompt,
                    status,
                    result_text,
                    error,
                    json.dumps(metadata or {}, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()

    def list_tasks(self, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM swarm_tasks"
        params: List[Any] = []
        if session_id:
            sql += " WHERE session_id = ?"
            params.append(session_id)
        sql += " ORDER BY created_at ASC"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]
