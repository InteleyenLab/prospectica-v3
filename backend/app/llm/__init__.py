"""Paquete unificado LLM dentro del repositorio (sin parches en site-packages)."""

from .camel_adapter import CamelGatewayModel, build_simulation_camel_model
from .gateway import (
    EXHAUSTED_MODELS,
    FALLBACK_MODELS,
    UnifiedLLMGateway,
    acreate_chat_completion,
    create_chat_completion,
    extract_chat_completion_text,
    get_candidate_models,
    is_gpt5_family,
)
from .structured_output import LLMResponseError, clean_chat_text
from .token_budget import BudgetProfile, BudgetProfiles, TokenBudgetManager

__all__ = [
    "BudgetProfile",
    "BudgetProfiles",
    "CamelGatewayModel",
    "EXHAUSTED_MODELS",
    "FALLBACK_MODELS",
    "LLMResponseError",
    "TokenBudgetManager",
    "UnifiedLLMGateway",
    "acreate_chat_completion",
    "build_simulation_camel_model",
    "clean_chat_text",
    "create_chat_completion",
    "extract_chat_completion_text",
    "get_candidate_models",
    "is_gpt5_family",
]
