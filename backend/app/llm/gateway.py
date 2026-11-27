"""
Gateway unificado síncrono/asíncrono compatible con FreeLLMAPI, OpenAI y GPT-5.
Centraliza en el repositorio la resiliencia ante errores 404, 413, 429 y 502-504.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from openai import AsyncOpenAI, OpenAI

from ..config import Config
from .structured_output import (
    clean_chat_text,
    execute_chat_json_with_retries,
)
from .token_budget import BudgetProfile, BudgetProfiles, TokenBudgetManager

logger = logging.getLogger(__name__)

FALLBACK_MODELS = [
    "auto",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "qwen/qwen3.8-27b",
]

EXHAUSTED_MODELS: Dict[str, float] = {}


def get_candidate_models(requested_model: str) -> List[str]:
    """Obtiene candidatos ordenados excluyendo modelos en enfriamiento TPD."""
    if requested_model and requested_model.strip().lower() == "auto":
        return ["auto"]

    now = time.time()
    for m in [k for k, exp in EXHAUSTED_MODELS.items() if now > exp]:
        del EXHAUSTED_MODELS[m]

    candidates = [requested_model] if requested_model else []
    for fb in FALLBACK_MODELS:
        if fb not in candidates:
            candidates.append(fb)

    available = [m for m in candidates if m not in EXHAUSTED_MODELS]
    return available if available else candidates


def is_gpt5_family(model: Optional[str]) -> bool:
    """Retorna True cuando el modelo pertenece a la familia GPT-5."""
    if not model:
        return False
    return model.strip().lower().startswith("gpt-5")


def _extract_error_meta(exc: Exception) -> tuple[Optional[int], str, str]:
    status_code = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    error_code = ""
    if isinstance(body, dict):
        details = body.get("error", body)
        if isinstance(details, dict):
            error_code = str(details.get("code") or "").strip().lower()
    return status_code, error_code, str(exc)


def _classify_error(exc: Exception) -> tuple[bool, bool, bool, bool, bool]:
    """Clasifica error en (is_tpd, is_413, is_model_not_found, is_rate_limited, is_transient_server)."""
    status_code, error_code, err_msg = _extract_error_meta(exc)
    low = err_msg.lower()

    is_tpd = (
        "TPD" in err_msg
        or "tokens per day" in low
        or "daily limit" in low
    )
    is_413 = (
        status_code == 413
        or "413" in err_msg
        or "payload too large" in low
        or "request too large" in low
        or "request entity too large" in low
        or "context_length_exceeded" in low
    )
    is_model_not_found = (
        status_code == 404
        or "404" in err_msg
        or "model_not_found" in low
        or ("invalid_request_error" in low and ("not found" in low or "not known" in low))
    )
    is_rate_limited = (
        "tokens per minute" in low
        or "TPM" in err_msg
        or "429" in err_msg
        or "routing_exhausted" in low
        or (status_code == 429 and error_code != "invalid_request")
    )
    is_transient_server = (
        status_code in {502, 503, 504}
        or "502" in err_msg
        or "503" in err_msg
        or "504" in err_msg
        or "upstream_failed" in low
        or "provider_error" in low
        or "timeout" in low
    )
    return is_tpd, is_413, is_model_not_found, is_rate_limited, is_transient_server


def _build_request_kwargs(
    *,
    candidate: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float],
    max_tokens: Optional[int],
    response_format: Optional[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    tool_choice: Optional[Any],
    extra_kwargs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "model": candidate,
        "messages": messages,
    }
    is_auto = candidate.strip().lower() == "auto"

    if response_format is not None and not is_auto:
        kwargs["response_format"] = response_format

    if tools is not None:
        kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

    gpt5 = is_gpt5_family(candidate)
    if temperature is not None and not gpt5:
        kwargs["temperature"] = temperature

    if max_tokens is not None:
        if gpt5:
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens

    if extra_kwargs:
        for k, v in extra_kwargs.items():
            if k not in kwargs and v is not None:
                kwargs[k] = v

    return kwargs


def _compute_backoff_seconds(
    *,
    attempt: int,
    is_413: bool,
    is_model_not_found: bool,
    is_rate_limited: bool,
) -> float:
    if is_413:
        return 0.5
    if is_model_not_found:
        return 2.0
    if is_rate_limited:
        return float(min(30, 6 * (attempt + 1)))
    return float(min(20, 4 * (attempt + 1)))


def create_chat_completion(
    client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    max_retries: int = 8,
    sleep_fn: Callable[[float], None] = time.sleep,
    extra_kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    """Envía una solicitud Chat Completions con recuperación ante 413/429/404/5xx y fallback controlado."""
    candidates = get_candidate_models(model)
    last_exception: Optional[Exception] = None
    attempts_limit = max(1, max_retries)

    for candidate in candidates:
        current_messages = list(messages)
        current_max_tokens = max_tokens

        for attempt in range(attempts_limit):
            kwargs = _build_request_kwargs(
                candidate=candidate,
                messages=current_messages,
                temperature=temperature,
                max_tokens=current_max_tokens,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                extra_kwargs=extra_kwargs,
            )
            try:
                return client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_exception = exc
                is_tpd, is_413, is_model_not_found, is_rate_limited, is_transient_server = _classify_error(exc)

                if is_tpd:
                    logger.warning(
                        "[Auto-Fallback] El modelo '%s' agotó cuota (TPD). Cambiando al siguiente candidato...",
                        candidate,
                    )
                    EXHAUSTED_MODELS[candidate] = time.time() + 60
                    break

                is_recoverable = is_413 or is_model_not_found or is_rate_limited or is_transient_server
                if not is_recoverable:
                    logger.error(f"[Gateway] Error no transitorio en modelo {candidate}: {exc}")
                    raise

                if attempt < attempts_limit - 1:
                    if is_413 or is_rate_limited:
                        current_messages, shrunk = TokenBudgetManager.shrink_on_413(
                            current_messages,
                            current_max_tokens,
                        )
                        if shrunk is not None:
                            current_max_tokens = shrunk
                    wait_seconds = _compute_backoff_seconds(
                        attempt=attempt,
                        is_413=is_413,
                        is_model_not_found=is_model_not_found,
                        is_rate_limited=is_rate_limited,
                    )
                    logger.warning(
                        "[Auto-Retry] Error recuperable en modelo '%s' (%s). Reintentando en %.1fs (%s/%s)...",
                        candidate,
                        str(exc)[:120],
                        wait_seconds,
                        attempt + 1,
                        attempts_limit,
                    )
                    sleep_fn(wait_seconds)
                    continue

                logger.warning(
                    "[Auto-Fallback] El modelo '%s' falló tras %s intentos; probando siguiente respaldo.",
                    candidate,
                    attempts_limit,
                )
                EXHAUSTED_MODELS[candidate] = time.time() + 30
                break

    if last_exception is not None:
        raise last_exception
    raise RuntimeError("No candidate LLM model succeeded")


async def acreate_chat_completion(
    async_client: Any,
    *,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    response_format: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    max_retries: int = 8,
    extra_kwargs: Optional[Dict[str, Any]] = None,
) -> Any:
    """Versión asíncrona de create_chat_completion con recuperación ante 413/429/404/5xx."""
    candidates = get_candidate_models(model)
    last_exception: Optional[Exception] = None
    attempts_limit = max(1, max_retries)

    for candidate in candidates:
        current_messages = list(messages)
        current_max_tokens = max_tokens

        for attempt in range(attempts_limit):
            kwargs = _build_request_kwargs(
                candidate=candidate,
                messages=current_messages,
                temperature=temperature,
                max_tokens=current_max_tokens,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                extra_kwargs=extra_kwargs,
            )
            try:
                return await async_client.chat.completions.create(**kwargs)
            except Exception as exc:
                last_exception = exc
                is_tpd, is_413, is_model_not_found, is_rate_limited, is_transient_server = _classify_error(exc)

                if is_tpd:
                    EXHAUSTED_MODELS[candidate] = time.time() + 60
                    break

                is_recoverable = is_413 or is_model_not_found or is_rate_limited or is_transient_server
                if not is_recoverable:
                    raise

                if attempt < attempts_limit - 1:
                    if is_413 or is_rate_limited:
                        current_messages, shrunk = TokenBudgetManager.shrink_on_413(
                            current_messages,
                            current_max_tokens,
                        )
                        if shrunk is not None:
                            current_max_tokens = shrunk
                    wait_seconds = _compute_backoff_seconds(
                        attempt=attempt,
                        is_413=is_413,
                        is_model_not_found=is_model_not_found,
                        is_rate_limited=is_rate_limited,
                    )
                    await asyncio.sleep(wait_seconds)
                    continue

                EXHAUSTED_MODELS[candidate] = time.time() + 30
                break

    if last_exception is not None:
        raise last_exception
    raise RuntimeError("No candidate LLM model succeeded")


def extract_chat_completion_text(response: Any) -> str:
    """Extrae texto plano de una respuesta ChatCompletion en distintas variantes de SDK."""
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""

    message = getattr(choices[0], "message", None)
    if message is None:
        return ""

    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        import json

        xml_parts = []
        for tc in tool_calls:
            fn = getattr(tc, "function", None)
            if fn:
                name = getattr(fn, "name", "")
                args_str = getattr(fn, "arguments", "{}")
                try:
                    args_obj = json.loads(args_str)
                except Exception:
                    args_obj = {"query": str(args_str)}
                xml_parts.append(
                    f'<tool_call>{{"name": "{name}", "parameters": {json.dumps(args_obj, ensure_ascii=False)}}}</tool_call>'
                )
        if xml_parts:
            return "\n".join(xml_parts)

    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, dict):
                text_obj = item.get("text")
                if isinstance(text_obj, dict):
                    text_obj = text_obj.get("value")
                if isinstance(text_obj, str):
                    chunks.append(text_obj)
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
                continue

            text_obj = getattr(item, "text", None)
            if isinstance(text_obj, dict):
                text_obj = text_obj.get("value")
            if isinstance(text_obj, str):
                chunks.append(text_obj)
                continue

            content_obj = getattr(item, "content", None)
            if isinstance(content_obj, str):
                chunks.append(content_obj)

        return "".join(chunks).strip()

    return str(content or "")


class UnifiedLLMGateway:
    """Fachada unificada de ejecución LLM con presupuesto de tokens y JSON estructurado."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        client: Optional[Any] = None,
        async_client: Optional[Any] = None,
        timeout: Optional[float] = 120.0,
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        if not self.api_key and client is None:
            raise ValueError("LLM_API_KEY no configurada")
        self.client = client or OpenAI(api_key=self.api_key, base_url=self.base_url, timeout=timeout)
        self._async_client = async_client
        self._timeout = timeout

    @property
    def async_client(self) -> Any:
        if self._async_client is None:
            self._async_client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self._timeout,
            )
        return self._async_client

    def create_completion(
        self,
        *,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        budget_profile: Optional[BudgetProfile] = None,
        max_retries: int = 8,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> Any:
        prepared = (
            TokenBudgetManager.fit_to_profile(messages, budget_profile)
            if budget_profile is not None
            else messages
        )
        return create_chat_completion(
            self.client,
            model=self.model,
            messages=prepared,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            max_retries=max_retries,
            sleep_fn=sleep_fn,
        )

    async def acreate_completion(
        self,
        *,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        budget_profile: Optional[BudgetProfile] = None,
        max_retries: int = 8,
    ) -> Any:
        prepared = (
            TokenBudgetManager.fit_to_profile(messages, budget_profile)
            if budget_profile is not None
            else messages
        )
        return await acreate_chat_completion(
            self.async_client,
            model=self.model,
            messages=prepared,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            max_retries=max_retries,
        )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 2000,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        budget_profile: Optional[BudgetProfile] = BudgetProfiles.DEFAULT,
    ) -> str:
        response = self.create_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            budget_profile=budget_profile,
        )
        return clean_chat_text(extract_chat_completion_text(response))

    async def achat(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 2000,
        response_format: Optional[Dict[str, Any]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[Any] = None,
        budget_profile: Optional[BudgetProfile] = BudgetProfiles.DEFAULT,
    ) -> str:
        response = await self.acreate_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            budget_profile=budget_profile,
        )
        return clean_chat_text(extract_chat_completion_text(response))

    def chat_json(
        self,
        messages: List[Dict[str, Any]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = 4096,
        max_attempts: int = 3,
        repair_on_final: bool = False,
        schema: Optional[Any] = None,
    ) -> Dict[str, Any]:
        return execute_chat_json_with_retries(
            lambda msgs, cap, rf: self.create_completion(
                messages=msgs,
                temperature=temperature,
                max_tokens=cap,
                response_format=rf,
            ),
            extract_chat_completion_text,
            messages=messages,
            max_tokens=max_tokens,
            max_attempts=max_attempts,
            repair_on_final=repair_on_final,
            schema=schema,
        )
