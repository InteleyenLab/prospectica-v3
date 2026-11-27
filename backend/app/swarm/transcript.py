"""Persistencia de transcripciones del enjambre en `swarm_memory/channel_transcript.jsonl`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state import SwarmMessage, SwarmSessionState


class SwarmTranscript:
    """Almacena sesiones y mensajes en servidor sobreviviendo reinicios de Flask/navegador."""

    def __init__(self, sim_dir: Path):
        self.swarm_dir = Path(sim_dir) / "swarm_memory"
        self.swarm_dir.mkdir(parents=True, exist_ok=True)
        self.transcript_path = self.swarm_dir / "channel_transcript.jsonl"
        self.sessions_path = self.swarm_dir / "sessions.json"

    def append_message(self, msg: SwarmMessage) -> None:
        with self.transcript_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(msg.to_dict(), ensure_ascii=False) + "\n")

    def list_messages(self, session_id: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        if not self.transcript_path.exists():
            return []
        rows: List[Dict[str, Any]] = []
        for line in self.transcript_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if session_id and item.get("session_id") != session_id:
                continue
            rows.append(item)
        return rows[-limit:]

    def save_session(self, session: SwarmSessionState) -> None:
        all_sessions = self._load_sessions_map()
        all_sessions[session.session_id] = session.to_dict()
        self.sessions_path.write_text(
            json.dumps(all_sessions, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_session(self, session_id: str) -> Optional[SwarmSessionState]:
        data = self._load_sessions_map().get(session_id)
        if not data:
            return None
        return SwarmSessionState(
            session_id=data["session_id"],
            simulation_id=data["simulation_id"],
            active_recipient=data.get("active_recipient", "ModeratorCommander"),
            known_agents=data.get("known_agents", []),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )

    def list_sessions(self) -> List[Dict[str, Any]]:
        return list(self._load_sessions_map().values())

    def _load_sessions_map(self) -> Dict[str, Any]:
        if not self.sessions_path.exists():
            return {}
        try:
            data = json.loads(self.sessions_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
