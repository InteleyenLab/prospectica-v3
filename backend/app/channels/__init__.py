"""Paquete de simulación multicanal colombiana/LATAM + adaptador legado OASIS."""

from .base import (
    CANONICAL_CHANNEL_IDS,
    LEGACY_CHANNEL_IDS,
    ChannelAction,
    ChannelAdapter,
    ChannelConfig,
    ChannelEvent,
    ChannelMessage,
    ChannelRegistry,
    InteractionTopology,
)
from .persistence import ChannelSQLiteStore, JSONLAppender
from .zep_bridge import ZepChannelBridge

__all__ = [
    "CANONICAL_CHANNEL_IDS",
    "LEGACY_CHANNEL_IDS",
    "ChannelAction",
    "ChannelAdapter",
    "ChannelConfig",
    "ChannelEvent",
    "ChannelMessage",
    "ChannelRegistry",
    "ChannelSQLiteStore",
    "InteractionTopology",
    "JSONLAppender",
    "ZepChannelBridge",
]
