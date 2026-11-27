"""
Presupuesto y compactación jerárquica de tokens para llamadas LLM.
Evita errores HTTP 413 (Payload Too Large) mediante estimación pre-vuelo y recorte progresivo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple


@dataclass(frozen=True)
class BudgetProfile:
    """Perfil de presupuesto de entrada/salida por tipo de tarea."""

    name: str
    max_input_tokens: int
    default_max_output_tokens: int


class BudgetProfiles:
    SIMULATION_TURN = BudgetProfile("simulation_turn", 3600, 900)
    SWARM_ORCHESTRATION = BudgetProfile("swarm_orchestration", 5500, 1800)
    REPORT_CHAPTER = BudgetProfile("report_chapter", 10500, 3200)
    DEFAULT = BudgetProfile("default", 12000, 4096)


class TokenBudgetManager:
    """Gestiona estimación de tokens, recorte pre-vuelo y recuperación ante 413."""

    @staticmethod
    def estimate_tokens(text: Optional[str]) -> int:
        if not text:
            return 0
        return math.ceil(len(str(text)) / 3.0) + 8

    @classmethod
    def estimate_message_tokens(cls, msg: Dict[str, Any]) -> int:
        content = msg.get("content", "")
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(str(item.get("text") or item.get("content") or ""))
                else:
                    parts.append(str(item))
            text_len = "\n".join(parts)
        else:
            text_len = str(content or "")
        tokens = cls.estimate_tokens(text_len) + 4
        if msg.get("tool_calls"):
            tokens += cls.estimate_tokens(str(msg["tool_calls"]))
        return tokens

    @classmethod
    def estimate_messages_tokens(cls, messages: Sequence[Dict[str, Any]]) -> int:
        return sum(cls.estimate_message_tokens(m) for m in messages) + 8

    @staticmethod
    def _clip_text(text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text
        if max_chars < 120:
            return text[:max_chars]
        head = int(max_chars * 0.72)
        tail = max_chars - head - 42
        marker = "\n... [recorte por límite de contexto] ...\n"
        if tail > 20:
            return text[:head].rstrip() + marker + text[-tail:].lstrip()
        return text[: max_chars - len(marker)].rstrip() + marker

    @classmethod
    def compact_messages(
        cls,
        messages: Sequence[Dict[str, Any]],
        *,
        target_ratio: float = 0.65,
        max_input_tokens: Optional[int] = None,
        min_keep_last: int = 2,
    ) -> List[Dict[str, Any]]:
        """Compacta mensajes preservando system prompt y los últimos turnos."""
        if not messages:
            return []

        cloned = [dict(m) for m in messages]
        current_tokens = cls.estimate_messages_tokens(cloned)
        limit_tokens = (
            max_input_tokens
            if max_input_tokens is not None
            else max(500, int(current_tokens * target_ratio))
        )
        if current_tokens <= limit_tokens:
            return cloned

        # 1. Separar system inicial, historial intermedio y últimos mensajes
        system_indices = [i for i, m in enumerate(cloned) if m.get("role") == "system"]
        non_system_indices = [i for i, m in enumerate(cloned) if m.get("role") != "system"]

        # Eliminar turnos intermedios más antiguos conservando min_keep_last
        keep_set = set(system_indices)
        tail_indices = non_system_indices[-min_keep_last:] if min_keep_last > 0 else []
        keep_set.update(tail_indices)

        # Conservar del historial reciente mientras quepa
        dropped = set()
        for idx in non_system_indices:
            if idx in tail_indices:
                continue
            if cls.estimate_messages_tokens([cloned[i] for i in range(len(cloned)) if i not in dropped]) <= limit_tokens:
                break
            dropped.add(idx)

        compacted = [cloned[i] for i in range(len(cloned)) if i not in dropped]
        current_tokens = cls.estimate_messages_tokens(compacted)
        if current_tokens <= limit_tokens:
            return compacted

        # 2. Si aún supera el presupuesto, recortar contenido textual proporcionalmente
        char_budget = max(800, int(limit_tokens * 2.6))
        total_chars = sum(len(str(m.get("content") or "")) for m in compacted if isinstance(m.get("content"), str))
        if total_chars > char_budget and total_chars > 0:
            scale = char_budget / float(total_chars)
            result: List[Dict[str, Any]] = []
            for idx, msg in enumerate(compacted):
                content = msg.get("content")
                if isinstance(content, str) and len(content) > 200:
                    # Dar algo más de peso al último mensaje del usuario
                    weight = 1.2 if idx == len(compacted) - 1 else 1.0
                    allowed = max(180, int(len(content) * scale * weight))
                    if allowed < len(content):
                        msg = {**msg, "content": cls._clip_text(content, allowed)}
                result.append(msg)
            return result

        return compacted

    @classmethod
    def fit_to_profile(
        cls,
        messages: Sequence[Dict[str, Any]],
        profile: BudgetProfile = BudgetProfiles.DEFAULT,
    ) -> List[Dict[str, Any]]:
        """Aplica recorte pre-vuelo si excede el perfil de presupuesto."""
        return cls.compact_messages(
            messages,
            max_input_tokens=profile.max_input_tokens,
            min_keep_last=2,
        )

    @classmethod
    def shrink_on_413(
        cls,
        messages: Sequence[Dict[str, Any]],
        max_tokens: Optional[int],
        *,
        target_ratio: float = 0.65,
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """Reduce ventana de entrada y max_tokens tras error HTTP 413."""
        new_max_tokens = (
            max(400, int(max_tokens * 0.70))
            if isinstance(max_tokens, int) and max_tokens > 400
            else max_tokens
        )
        new_messages = cls.compact_messages(messages, target_ratio=target_ratio, min_keep_last=2)
        return new_messages, new_max_tokens
