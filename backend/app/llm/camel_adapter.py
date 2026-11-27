"""
Adaptador de modelo CAMEL-AI versionado en el repositorio.
Sustituye los parches manuales sobre site-packages/camel/models/openai_model.py,
enrutando todas las rondas de simulación a través de UnifiedLLMGateway y TokenBudgetManager.
"""

from __future__ import annotations

import copy
import os
from typing import Any, Dict, List, Optional, Union

from camel.models.openai_model import OpenAIModel

from .gateway import acreate_chat_completion, create_chat_completion
from .token_budget import BudgetProfiles, TokenBudgetManager


class CamelGatewayModel(OpenAIModel):
    """Subclase versionada de OpenAIModel con presupuesto pre-vuelo y recuperación ante 413/429/5xx."""

    def _prepare_gateway_args(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
        cfg = copy.deepcopy(self.model_config_dict or {})
        if tools:
            cfg["tools"] = tools
        cfg = self._sanitize_config(cfg)

        temperature = cfg.pop("temperature", None)
        max_tokens = cfg.pop("max_tokens", None) or cfg.pop("max_completion_tokens", None)
        response_format = cfg.pop("response_format", None)
        req_tools = cfg.pop("tools", None)
        tool_choice = cfg.pop("tool_choice", None)

        fitted_messages = TokenBudgetManager.fit_to_profile(
            messages,
            BudgetProfiles.SIMULATION_TURN,
        )
        return fitted_messages, {
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": response_format,
            "tools": req_tools,
            "tool_choice": tool_choice,
            "extra_kwargs": cfg,
        }

    def _request_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        fitted_messages, params = self._prepare_gateway_args(messages, tools)
        return create_chat_completion(
            self._client,
            model=str(self.model_type),
            messages=fitted_messages,
            max_retries=6,
            **params,
        )

    async def _arequest_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Any:
        fitted_messages, params = self._prepare_gateway_args(messages, tools)
        return await acreate_chat_completion(
            self._async_client,
            model=str(self.model_type),
            messages=fitted_messages,
            max_retries=6,
            **params,
        )


def build_simulation_camel_model(
    model_type: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 120.0,
) -> CamelGatewayModel:
    """Construye el modelo CAMEL para simulaciones leyendo las variables activas si no se pasan."""
    resolved_model = (model_type or os.environ.get("LLM_MODEL_NAME") or "auto").strip()
    resolved_key = api_key or os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    resolved_url = base_url or os.environ.get("LLM_BASE_URL") or os.environ.get("OPENAI_API_BASE_URL")
    return CamelGatewayModel(
        model_type=resolved_model,
        api_key=resolved_key,
        url=resolved_url,
        timeout=timeout,
    )
