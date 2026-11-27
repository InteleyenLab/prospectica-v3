"""Modelos de estado, turnos y resultados del enjambre Orkas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class TurnOutcome:
    """Resultado explícito de un turno (soporta silencio tras handoff sin burbuja vacía)."""

    kind: str  # "reply" | "silent" | "dispatch" | "handoff"
    content: str = ""
    active_recipient: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SwarmMessage:
    """Mensaje persistible en `channel_transcript.jsonl`."""

    message_id: str
    session_id: str
    from_kind: str  # "human" | "commander" | "agent" | "worker" | "system"
    sender_name: str
    recipient_name: str
    content: str
    mentions: List[str] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    outcome_kind: str = "reply"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SwarmSessionState:
    """Estado de una sesión persistente del enjambre."""

    session_id: str
    simulation_id: str
    active_recipient: str = "ModeratorCommander"
    known_agents: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
