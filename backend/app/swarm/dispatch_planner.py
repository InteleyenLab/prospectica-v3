"""Planificador determinístico de despacho DAG acíclico (máximo 8 subtareas)."""

from __future__ import annotations

from collections import deque
from typing import Any, Dict, List


class DAGCycleError(ValueError):
    """Se lanza cuando las dependencias del plan de despacho contienen un ciclo o referencia inválida."""


class DispatchPlanner:
    """Valida límite de subtareas (<= 8), ausencia de ciclos y genera orden topológico por capas."""

    MAX_SUBTASKS = 8

    @classmethod
    def validate_and_toposort(cls, subtasks: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Valida `subtasks = [{id, target, prompt, depends_on?}]` y retorna oleadas paralelas acíclicas."""
        if not subtasks:
            return []
        if len(subtasks) > cls.MAX_SUBTASKS:
            raise ValueError(f"Máximo {cls.MAX_SUBTASKS} subtareas por despacho (recibidas: {len(subtasks)})")

        by_id: Dict[str, Dict[str, Any]] = {}
        in_degree: Dict[str, int] = {}
        dependents: Dict[str, List[str]] = {}

        for raw in subtasks:
            tid = str(raw.get("id") or raw.get("task_id") or "").strip()
            if not tid:
                raise ValueError("Toda subtarea requiere un campo 'id' no vacío")
            if tid in by_id:
                raise ValueError(f"ID de subtarea duplicado: {tid}")
            by_id[tid] = dict(raw)
            by_id[tid]["id"] = tid
            in_degree[tid] = 0
            dependents[tid] = []

        for tid, task in by_id.items():
            deps = task.get("depends_on") or []
            for dep in deps:
                dep_id = str(dep).strip()
                if dep_id == tid:
                    raise DAGCycleError(f"Auto-ciclo detectado en subtarea '{tid}'")
                if dep_id not in by_id:
                    raise DAGCycleError(f"Dependencia inexistente '{dep_id}' referenciada por '{tid}'")
                dependents[dep_id].append(tid)
                in_degree[tid] += 1

        # Kahn por oleadas (capas ejecutables en paralelo)
        queue = deque([tid for tid, deg in in_degree.items() if deg == 0])
        waves: List[List[Dict[str, Any]]] = []
        visited = 0

        while queue:
            wave_size = len(queue)
            wave: List[Dict[str, Any]] = []
            for _ in range(wave_size):
                curr = queue.popleft()
                visited += 1
                wave.append(by_id[curr])
                for nxt in dependents[curr]:
                    in_degree[nxt] -= 1
                    if in_degree[nxt] == 0:
                        queue.append(nxt)
            waves.append(wave)

        if visited != len(by_id):
            raise DAGCycleError("Ciclo detectado en el grafo DAG de subtareas")

        return waves
