"""Enrutamiento anti-bucles: solo mensajes humanos disparan @menciones multi-palabra."""

from __future__ import annotations

import re
from typing import Iterable, List

MENTION_SIMPLE_RE = re.compile(r"@([A-Za-z0-9_ÁÉÍÓÚÜÑáéíóúüñ-]+)")


def parse_mentions(
    text: str,
    from_kind: str,
    known_agents: Optional[Iterable[str]] = None,
) -> List[str]:
    """Extrae `@menciones` únicamente cuando `from_kind == 'human'`; agentes/commander retornan `[]`."""
    if (from_kind or "").strip().lower() != "human":
        return []
    if not text:
        return []

    found: List[str] = []
    # 1. Emparejar nombres completos multi-palabra de agentes conocidos (ej. `@María Fernanda`)
    known = sorted({str(a).strip() for a in (known_agents or []) if str(a).strip()}, key=len, reverse=True)
    text_lower = text.lower()
    for name in known:
        token = f"@{name.lower()}"
        idx = text_lower.find(token)
        if idx >= 0:
            after = idx + len(token)
            if after >= len(text_lower) or not text_lower[after].isalnum():
                if name not in found:
                    found.append(name)

    # 2. Emparejar tokens simples `@username` si no quedaron ya cubiertos
    for match in MENTION_SIMPLE_RE.finditer(text):
        cand = match.group(1).strip()
        if not cand:
            continue
        if any(f.lower().startswith(cand.lower()) for f in found):
            continue
        if cand not in found:
            found.append(cand)

    return found
