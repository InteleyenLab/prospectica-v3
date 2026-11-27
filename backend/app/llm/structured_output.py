"""
Utilidades de salida JSON estructurada, limpieza de razonamiento y reparación tolerante.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Type

logger = logging.getLogger(__name__)


class LLMResponseError(ValueError):
    """Error seguro y estructurado para respuestas inutilizables del LLM."""

    def __init__(self, message: str, *, finish_reason: Optional[str] = None):
        super().__init__(message)
        self.finish_reason = finish_reason


def is_response_format_unsupported(error: Exception) -> bool:
    """Detecta rechazo explícito del proveedor para el parámetro response_format."""
    if getattr(error, "status_code", None) not in {400, 422}:
        return False

    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return False

    details = body.get("error", body)
    if not isinstance(details, dict):
        return False

    param = str(details.get("param") or "").strip().lower()
    if param == "response_format" or param.startswith("response_format."):
        return True

    message = str(details.get("message") or "").lower()
    if "response_format" not in message:
        return False

    code = str(details.get("code") or "").lower()
    unsupported_codes = {
        "unsupported_parameter",
        "unsupported_value",
        "unknown_parameter",
        "invalid_parameter",
    }
    unsupported_phrases = (
        "not support",
        "unsupported",
        "unknown parameter",
        "unrecognized parameter",
    )
    return code in unsupported_codes or any(phrase in message for phrase in unsupported_phrases)


def clean_chat_text(content: str) -> str:
    """Elimina bloques <think> y envoltorios Markdown ```json ```."""
    if not content:
        return ""
    cleaned = re.sub(r"<think>[\s\S]*?</think>", "", content, flags=re.IGNORECASE).strip()
    if "</think>" in cleaned.lower():
        cleaned = re.split(r"</think>", cleaned, flags=re.IGNORECASE)[-1].strip()
    cleaned = cleaned.lstrip("\ufeff")
    if not cleaned.startswith(("{", "[")):
        fenced_match = re.search(
            r"```(?:json\s*\n?([\s\S]*?)|\s*\n?(\s*[\[{][\s\S]*?))\n?```",
            cleaned,
            flags=re.IGNORECASE,
        )
        if fenced_match:
            inner = fenced_match.group(1) or fenced_match.group(2)
            if inner is not None:
                return inner.strip()
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    return cleaned.strip()


def contains_additional_json_container(content: str) -> bool:
    """Retorna True si el texto restante incrusta otro objeto o arreglo JSON."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", content):
        try:
            value, _ = decoder.raw_decode(content[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(value, (dict, list)):
            return True
    return False


def try_repair_truncated_json(text: str) -> Optional[Dict[str, Any]]:
    """Intenta recuperar un objeto JSON truncado cerrando comillas y llaves."""
    if not text or not isinstance(text, str):
        return None
    start_idx = text.find("{")
    if start_idx == -1:
        return None
    raw = text[start_idx:].strip()

    try:
        val = json.loads(raw)
        if isinstance(val, dict):
            return val
    except Exception:
        pass

    candidates = [raw]
    for cut_char in ["},", "}", "],", "]"]:
        pos = raw.rfind(cut_char)
        if pos != -1:
            candidates.append(raw[: pos + len(cut_char.rstrip(","))])

    for candidate in candidates:
        in_string = False
        escaped = False
        clean_chars = []
        for ch in candidate:
            if ch == "\\" and not escaped:
                escaped = True
                clean_chars.append(ch)
                continue
            if ch == '"' and not escaped:
                in_string = not in_string
            escaped = False
            clean_chars.append(ch)

        balanced = "".join(clean_chars)
        if in_string:
            balanced += '"'

        stack = []
        in_str = False
        esc = False
        for ch in balanced:
            if ch == "\\" and not esc:
                esc = True
                continue
            if ch == '"' and not esc:
                in_str = not in_str
            elif not in_str:
                if ch in ("{", "["):
                    stack.append(ch)
                elif ch in ("}", "]"):
                    if stack:
                        top = stack[-1]
                        if (top == "{" and ch == "}") or (top == "[" and ch == "]"):
                            stack.pop()
            esc = False

        while stack:
            top = stack.pop()
            if top == "{":
                balanced += "}"
            elif top == "[":
                balanced += "]"

        try:
            val = json.loads(balanced)
            if isinstance(val, dict) and len(val) > 0:
                return val
        except Exception:
            continue
    return None


def parse_json_completion(
    raw_text: str,
    *,
    finish_reason: Optional[str] = None,
    has_choices: bool = True,
    allow_repair_on_length: bool = False,
    schema: Optional[Type[Any]] = None,
) -> Dict[str, Any]:
    """Parsea una respuesta textual como JSON objeto con validación estricta o reparación controlada."""
    if not has_choices:
        raise LLMResponseError("LLM returned no choices")

    content = clean_chat_text(raw_text)
    if not content:
        raise LLMResponseError("LLM returned empty JSON content", finish_reason=finish_reason)

    if finish_reason == "length":
        if allow_repair_on_length:
            repaired = try_repair_truncated_json(content)
            if repaired and isinstance(repaired, dict) and len(repaired) > 0:
                logger.warning("LLM JSON output was truncated by token limit, repaired on final attempt.")
                return _validate_schema(repaired, schema, finish_reason)
        raise LLMResponseError("LLM JSON output was truncated at the token limit", finish_reason=finish_reason)

    if finish_reason not in {None, "stop"}:
        raise LLMResponseError(
            f"LLM JSON generation stopped unexpectedly ({finish_reason})",
            finish_reason=finish_reason,
        )

    try:
        value = json.loads(content)
    except json.JSONDecodeError as strict_error:
        try:
            value, end = json.JSONDecoder().raw_decode(content)
        except json.JSONDecodeError:
            repaired = try_repair_truncated_json(content)
            if repaired and isinstance(repaired, dict) and len(repaired) > 0:
                logger.warning("Repaired malformed JSON response from LLM")
                return _validate_schema(repaired, schema, finish_reason)
            raise LLMResponseError(
                f"LLM returned invalid JSON (line {strict_error.lineno}, column {strict_error.colno})",
                finish_reason=finish_reason,
            ) from strict_error

        trailing = content[end:].strip()
        if trailing:
            if contains_additional_json_container(trailing):
                raise LLMResponseError("LLM returned multiple JSON values", finish_reason=finish_reason)
            logger.warning("Ignoring text after a complete LLM JSON object")

    if not isinstance(value, dict):
        raise LLMResponseError("LLM JSON response must be a top-level JSON object", finish_reason=finish_reason)

    return _validate_schema(value, schema, finish_reason)


def _validate_schema(
    value: Dict[str, Any],
    schema: Optional[Type[Any]],
    finish_reason: Optional[str],
) -> Dict[str, Any]:
    if schema is None:
        return value
    try:
        validated = schema.model_validate(value)
        return validated.model_dump()
    except Exception as exc:
        raise LLMResponseError(f"LLM JSON failed schema validation: {exc}", finish_reason=finish_reason) from exc


def execute_chat_json_with_retries(
    send_fn: Callable[[List[Dict[str, str]], Optional[int], Optional[Dict[str, Any]]], Any],
    extract_text_fn: Callable[[Any], str],
    *,
    messages: List[Dict[str, str]],
    max_tokens: Optional[int] = 4096,
    max_attempts: int = 3,
    repair_on_final: bool = False,
    schema: Optional[Type[Any]] = None,
) -> Dict[str, Any]:
    """Ejecuta generación JSON con negociación de response_format y reintentos sin tope ante truncamiento."""
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    response_format: Optional[Dict[str, Any]] = {"type": "json_object"}
    has_json = any("json" in str(m.get("content", "")).lower() for m in messages)
    if not has_json and messages:
        messages = list(messages)
        messages[-1] = {
            **messages[-1],
            "content": str(messages[-1].get("content", "")) + "\nReturn output in valid JSON format.",
        }

    request_max_tokens = max_tokens
    last_error: Optional[LLMResponseError] = None

    for attempt in range(1, max_attempts + 1):
        while True:
            try:
                response = send_fn(messages, request_max_tokens, response_format)
            except Exception as error:
                if response_format is not None and is_response_format_unsupported(error):
                    logger.warning(
                        "LLM provider explicitly rejected response_format; "
                        "retrying once with prompt-only JSON guidance"
                    )
                    response_format = None
                    continue
                raise
            break

        choices = getattr(response, "choices", None) or []
        choice = choices[0] if choices else None
        finish_reason = getattr(choice, "finish_reason", None) if choice is not None else None
        raw_text = extract_text_fn(response) if choices else ""

        try:
            return parse_json_completion(
                raw_text,
                finish_reason=finish_reason,
                has_choices=bool(choices),
                allow_repair_on_length=(repair_on_final and attempt >= max_attempts),
                schema=schema,
            )
        except LLMResponseError as error:
            last_error = error
            if attempt >= max_attempts:
                raise
            had_token_cap = request_max_tokens is not None
            request_max_tokens = None
            logger.warning(
                "LLM returned unusable JSON (finish_reason=%s); retrying content generation%s",
                error.finish_reason or "unknown",
                " without an output token cap" if had_token_cap else "",
            )

    if last_error is not None:
        raise last_error
    raise LLMResponseError("LLM did not produce a JSON response")
