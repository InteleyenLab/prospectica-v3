"""Contratos base, topologías, eventos y registro de canales colombianos/LATAM."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Type

CANONICAL_CHANNEL_IDS: List[str] = [
    "whatsapp_1on1",
    "focus_group",
    "street_survey",
    "facebook_groups",
    "tiktok",
    "instagram",
    "news_portals",
    "colombian_web",
    "advertising",
    "tv",
    "radio",
]

LEGACY_CHANNEL_IDS: List[str] = ["legacy_twitter", "legacy_reddit"]


class InteractionTopology(str, Enum):
    """Topologías de interacción soportadas por los adaptadores multicanal."""

    PRIVATE_THREAD = "private_thread"
    MODERATED_GROUP = "moderated_group"
    FIELD_INTERCEPT = "field_intercept"
    COMMUNITY_BOARD = "community_board"
    SHORT_VIDEO_FEED = "short_video_feed"
    VISUAL_SOCIAL_FEED = "visual_social_feed"
    EDITORIAL_COMMENTS = "editorial_comments"
    WEB_FUNNEL = "web_funnel"
    BROADCAST_MEDIA = "broadcast_media"
    MICROBLOG_LEGACY = "microblog_legacy"


@dataclass
class ChannelConfig:
    """Metadatos descriptivos y de activación de un canal."""

    channel_id: str
    display_name: str
    category: str
    topology: InteractionTopology
    is_legacy: bool = False
    supports_media_exposure: bool = False
    default_enabled: bool = True
    description: str = ""
    peak_hours: List[int] = field(default_factory=lambda: [8, 9, 12, 13, 18, 19, 20, 21])

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["topology"] = self.topology.value
        return payload


@dataclass
class ChannelMessage:
    """Mensaje o estímulo entrante entregado a un adaptador de canal."""

    channel_id: str
    round_num: int
    simulated_hour: int
    prompt_or_topic: str
    sender_role: str = "moderador"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelAction:
    """Acción elemental normalizada emitida por un actor en un canal."""

    action_type: str
    content_text: str
    sentiment_score: float = 0.0
    objection_tag: Optional[str] = None
    is_friction: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelEvent:
    """Evento multicanal trazable para SQLite WAL, JSONL, Analytics y Zep."""

    actor_agent_id: int
    actor_name: str
    city_divipola: str
    city_name: str
    stratum_code: str
    region_macro: str
    attitude_segment: str
    channel_id: str
    round_num: int
    simulated_hour: int
    action_type: str
    content_text: str
    sentiment_score: float = 0.0
    objection_tag: Optional[str] = None
    is_friction: bool = False
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def format_zep_episode(self) -> str:
        """Formatea el evento 100% en español (0 caracteres CJK) para memoria Zep."""
        obj_part = f" [Objeción: {self.objection_tag}]" if self.objection_tag else ""
        return (
            f"[{self.channel_id} | Ronda {self.round_num} | {self.simulated_hour:02d}:00 COT] "
            f"{self.actor_name} ({self.city_name}, DIVIPOLA {self.city_divipola}, {self.stratum_code}, "
            f"postura {self.attitude_segment}) realizó {self.action_type}{obj_part}: "
            f"\"{self.content_text.strip()}\""
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ChannelAdapter(ABC):
    """Interfaz abstracta que deben implementar los 11 canales y el respaldo legado."""

    config: ChannelConfig

    @abstractmethod
    def simulate_round(
        self,
        actors: List[Dict[str, Any]],
        study_context: Dict[str, Any],
        round_num: int,
        simulated_hour: int,
    ) -> Dict[str, Any]:
        """Ejecuta una ronda del canal y retorna `{events, whatsapp_sessions, focus_group_turns, survey_responses, media_exposures}`."""


class ChannelRegistry:
    """Registro central de adaptadores disponibles."""

    _adapters: Dict[str, Type[ChannelAdapter]] = {}

    @classmethod
    def register(cls, adapter_cls: Type[ChannelAdapter]) -> Type[ChannelAdapter]:
        cls._adapters[adapter_cls.config.channel_id] = adapter_cls
        return adapter_cls

    @classmethod
    def get(cls, channel_id: str) -> ChannelAdapter:
        if channel_id not in cls._adapters:
            raise KeyError(f"Canal no registrado: {channel_id}")
        return cls._adapters[channel_id]()

    @classmethod
    def list_catalog(cls, include_legacy: bool = True) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        ordered_ids = CANONICAL_CHANNEL_IDS + (LEGACY_CHANNEL_IDS if include_legacy else [])
        for cid in ordered_ids:
            if cid in cls._adapters:
                items.append(cls._adapters[cid].config.to_dict())
        for cid, adapter_cls in cls._adapters.items():
            if cid not in ordered_ids:
                items.append(adapter_cls.config.to_dict())
        return items

    @classmethod
    def registered_ids(cls) -> List[str]:
        return list(cls._adapters.keys())
