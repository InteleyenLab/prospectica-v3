"""
任务状态管理
用于跟踪长时间运行的任务（如图谱构建）
"""

import json
import os
import sqlite3
import uuid
import threading
from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from ..config import Config
from ..utils.locale import t


class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"          # 等待中
    PROCESSING = "processing"    # 处理中
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败


@dataclass
class Task:
    """任务数据类"""
    task_id: str
    task_type: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
    progress: int = 0              # 总进度百分比 0-100
    message: str = ""              # 状态消息
    result: Optional[Dict] = None  # 任务结果
    error: Optional[str] = None    # 错误信息
    metadata: Dict = field(default_factory=dict)  # 额外元数据
    progress_detail: Dict = field(default_factory=dict)  # 详细进度信息
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "task_id": self.task_id,
            "task_type": self.task_type,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "progress": self.progress,
            "message": self.message,
            "progress_detail": self.progress_detail,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }


class TaskManager:
    """
    Gestor de tareas en memoria + persistencia SQLite (`system_tasks` con modo WAL).
    Permite recuperar el estado tras reinicios del servidor Flask.
    """

    _instance = None
    _lock = threading.Lock()
    DEFAULT_DB_PATH = os.path.join(Config.UPLOAD_FOLDER, "system_tasks.db")

    def __new__(cls, db_path: Optional[str] = None):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    inst = super().__new__(cls)
                    inst._tasks = {}
                    inst._task_lock = threading.Lock()
                    inst._db_path = db_path or cls.DEFAULT_DB_PATH
                    inst._init_db()
                    inst._load_from_db()
                    cls._instance = inst
        return cls._instance

    def _connect(self) -> sqlite3.Connection:
        os.makedirs(os.path.dirname(os.path.abspath(self._db_path)), exist_ok=True)
        conn = sqlite3.connect(self._db_path, timeout=15.0, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_tasks (
                    task_id TEXT PRIMARY KEY,
                    task_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    progress INTEGER DEFAULT 0,
                    message TEXT DEFAULT '',
                    result_json TEXT,
                    error TEXT,
                    metadata_json TEXT,
                    progress_detail_json TEXT
                )
                """
            )
            conn.commit()

    def _persist_task(self, task: Task):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO system_tasks (
                    task_id, task_type, status, created_at, updated_at,
                    progress, message, result_json, error, metadata_json, progress_detail_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at,
                    progress=excluded.progress,
                    message=excluded.message,
                    result_json=excluded.result_json,
                    error=excluded.error,
                    metadata_json=excluded.metadata_json,
                    progress_detail_json=excluded.progress_detail_json
                """,
                (
                    task.task_id,
                    task.task_type,
                    task.status.value,
                    task.created_at.isoformat(),
                    task.updated_at.isoformat(),
                    task.progress,
                    task.message,
                    json.dumps(task.result, ensure_ascii=False) if task.result is not None else None,
                    task.error,
                    json.dumps(task.metadata, ensure_ascii=False),
                    json.dumps(task.progress_detail, ensure_ascii=False),
                ),
            )
            conn.commit()

    def _load_from_db(self):
        if not os.path.exists(self._db_path):
            return
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT task_id, task_type, status, created_at, updated_at, progress, message, "
                "result_json, error, metadata_json, progress_detail_json FROM system_tasks"
            ).fetchall()
        for row in rows:
            (
                task_id, task_type, status, created_at, updated_at,
                progress, message, result_json, error, metadata_json, progress_detail_json
            ) = row
            self._tasks[task_id] = Task(
                task_id=task_id,
                task_type=task_type,
                status=TaskStatus(status),
                created_at=datetime.fromisoformat(created_at),
                updated_at=datetime.fromisoformat(updated_at),
                progress=progress or 0,
                message=message or "",
                result=json.loads(result_json) if result_json else None,
                error=error,
                metadata=json.loads(metadata_json) if metadata_json else {},
                progress_detail=json.loads(progress_detail_json) if progress_detail_json else {},
            )

    def create_task(self, task_type: str, metadata: Optional[Dict] = None) -> str:
        task_id = str(uuid.uuid4())
        now = datetime.now()
        task = Task(
            task_id=task_id,
            task_type=task_type,
            status=TaskStatus.PENDING,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )
        with self._task_lock:
            self._tasks[task_id] = task
            self._persist_task(task)
        return task_id

    def get_task(self, task_id: str) -> Optional[Task]:
        with self._task_lock:
            return self._tasks.get(task_id)

    def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict] = None,
        error: Optional[str] = None,
        progress_detail: Optional[Dict] = None,
    ):
        with self._task_lock:
            task = self._tasks.get(task_id)
            if task:
                task.updated_at = datetime.now()
                if status is not None:
                    task.status = status
                if progress is not None:
                    task.progress = progress
                if message is not None:
                    task.message = message
                if result is not None:
                    task.result = result
                if error is not None:
                    task.error = error
                if progress_detail is not None:
                    task.progress_detail = progress_detail
                self._persist_task(task)

    def complete_task(self, task_id: str, result: Dict):
        self.update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message=t("progress.taskComplete"),
            result=result,
        )

    def fail_task(self, task_id: str, error: str):
        self.update_task(
            task_id,
            status=TaskStatus.FAILED,
            message=t("progress.taskFailed"),
            error=error,
        )

    def list_tasks(self, task_type: Optional[str] = None) -> list:
        with self._task_lock:
            tasks = list(self._tasks.values())
            if task_type:
                tasks = [t_item for t_item in tasks if t_item.task_type == task_type]
            return [t_item.to_dict() for t_item in sorted(tasks, key=lambda x: x.created_at, reverse=True)]

    def cleanup_old_tasks(self, max_age_hours: int = 24):
        cutoff = datetime.now() - timedelta(hours=max_age_hours)
        with self._task_lock:
            old_ids = [
                tid
                for tid, task in self._tasks.items()
                if task.created_at < cutoff and task.status in [TaskStatus.COMPLETED, TaskStatus.FAILED]
            ]
            for tid in old_ids:
                del self._tasks[tid]
            if old_ids and os.path.exists(self._db_path):
                with self._connect() as conn:
                    conn.executemany("DELETE FROM system_tasks WHERE task_id = ?", [(tid,) for tid in old_ids])
                    conn.commit()

