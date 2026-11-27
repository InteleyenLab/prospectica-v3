"""
Compatibilidad OpenAI Chat Completions delegada al gateway unificado (`backend/app/llm/gateway.py`).
Mantiene intactas las firmas públicas heredadas.
"""

from __future__ import annotations

from ..llm.gateway import (
    EXHAUSTED_MODELS,
    FALLBACK_MODELS,
    create_chat_completion,
    extract_chat_completion_text,
    get_candidate_models,
    is_gpt5_family,
)

__all__ = [
    "EXHAUSTED_MODELS",
    "FALLBACK_MODELS",
    "create_chat_completion",
    "extract_chat_completion_text",
    "get_candidate_models",
    "is_gpt5_family",
]
