"""Puente de memoria Zep en español puro (0 literales CJK) para eventos multicanal."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from .base import ChannelEvent

PASSIVE_ACTION_TYPES = frozenset({"IDLE", "NO_OP", "SCROLL_PASSIVE"})
CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class ZepChannelBridge:
    """Filtra acciones pasivas y serializa episodios de canales en español limpio."""

    @staticmethod
    def should_index(event: ChannelEvent) -> bool:
        if event.action_type.upper() in PASSIVE_ACTION_TYPES:
            return False
        return bool((event.content_text or "").strip())

    @staticmethod
    def format_episode(event: ChannelEvent) -> str:
        text = event.format_zep_episode()
        return CJK_RE.sub("", text).strip()

    @classmethod
    def build_episode_batch(cls, events: List[ChannelEvent]) -> List[Dict[str, Any]]:
        episodes: List[Dict[str, Any]] = []
        for ev in events:
            if not cls.should_index(ev):
                continue
            episodes.append(
                {
                    "channel_id": ev.channel_id,
                    "round_num": ev.round_num,
                    "actor_agent_id": ev.actor_agent_id,
                    "city_divipola": ev.city_divipola,
                    "stratum_code": ev.stratum_code,
                    "episode_text": cls.format_episode(ev),
                }
            )
        return episodes
