"""Memoria compartida ligera por sesión y agente dentro de `swarm_memory/`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


class SwarmMemoryStore:
    """Guarda hechos clave y contexto resumido persistente por sesión del enjambre."""

    def __init__(self, sim_dir: Path):
        self.swarm_dir = Path(sim_dir) / "swarm_memory"
        self.swarm_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = self.swarm_dir / "shared_memory.json"

    def load(self) -> Dict[str, Any]:
        if not self.memory_path.exists():
            return {"notes": [], "actor_summaries": {}}
        try:
            return json.loads(self.memory_path.read_text(encoding="utf-8"))
        except Exception:
            return {"notes": [], "actor_summaries": {}}

    def append_note(self, note: str) -> None:
        data = self.load()
        notes = data.setdefault("notes", [])
        notes.append(note)
        data["notes"] = notes[-50:]
        self.memory_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
