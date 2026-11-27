"""Planificador concurrente anti-deadlock con doble semáforo independiente y locks por actor."""

from __future__ import annotations

import concurrent.futures
import threading
from typing import Any, Callable, Dict, List

from .dispatch_planner import DispatchPlanner


class SwarmScheduler:
    """Garantiza ejecución paralela sin interbloqueos usando semáforos separados (global vs worker)."""

    def __init__(self, global_slots: int = 2, nested_worker_slots: int = 4):
        self.global_slots = max(1, global_slots)
        self.nested_worker_slots = max(1, nested_worker_slots)
        self.llm_global_semaphore = threading.Semaphore(self.global_slots)
        self.nested_worker_semaphore = threading.Semaphore(self.nested_worker_slots)
        self._actor_locks: Dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def _get_actor_lock(self, actor_key: str) -> threading.Lock:
        with self._guard:
            if actor_key not in self._actor_locks:
                self._actor_locks[actor_key] = threading.Lock()
            return self._actor_locks[actor_key]

    def run_in_global_slot(self, fn: Callable[[], Any]) -> Any:
        with self.llm_global_semaphore:
            return fn()

    def run_nested_worker(self, actor_key: str, fn: Callable[[], Any]) -> Any:
        """Usa el semáforo independiente de workers anidados para nunca bloquear `llm_global_semaphore`."""
        actor_lock = self._get_actor_lock(actor_key)
        with self.nested_worker_semaphore:
            with actor_lock:
                return fn()

    def execute_dispatch_dag(
        self,
        subtasks: List[Dict[str, Any]],
        worker_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Valida DAG acíclico y ejecuta oleadas en paralelo sin deadlock incluso con `global_slots=2`."""
        waves = DispatchPlanner.validate_and_toposort(subtasks)
        all_results: List[Dict[str, Any]] = []

        for wave in waves:
            with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(wave))) as pool:
                future_map = {
                    pool.submit(
                        self.run_nested_worker,
                        str(task.get("target") or task["id"]),
                        lambda t=task: worker_fn(t),
                    ): task
                    for task in wave
                }
                for fut in concurrent.futures.as_completed(future_map):
                    all_results.append(fut.result())

        return all_results
