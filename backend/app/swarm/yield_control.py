"""Controlador cooperativo de cancelación para ejecuciones del enjambre."""

from __future__ import annotations

import threading
from typing import Dict


class YieldCancelledError(RuntimeError):
    """Excepción controlada al cancelar cooperativamente una ejecución."""


class YieldController:
    def __init__(self):
        self._events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()

    def get_flag(self, key: str) -> threading.Event:
        with self._lock:
            if key not in self._events:
                self._events[key] = threading.Event()
            return self._events[key]

    def request_yield(self, key: str) -> None:
        self.get_flag(key).set()

    def check_yield(self, key: str) -> None:
        if self.get_flag(key).is_set():
            raise YieldCancelledError(f"Ejecución cancelada cooperativamente ({key})")
