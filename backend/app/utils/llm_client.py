"""
LLM客户端封装
统一使用OpenAI格式调用
"""

import json
import logging
import re
from typing import Optional, Dict, Any, List
from openai import OpenAI

from ..config import Config
from .openai_chat_compat import create_chat_completion, extract_chat_completion_text


logger = logging.getLogger(__name__)


from ..llm.structured_output import (
    LLMResponseError,
    clean_chat_text as _clean_chat_text,
    contains_additional_json_container as _contains_additional_json_container,
    execute_chat_json_with_retries,
    is_response_format_unsupported as _is_response_format_unsupported,
    parse_json_completion,
    try_repair_truncated_json as _try_repair_truncated_json,
)


class LLMClient:
    """LLM客户端"""
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY 未配置")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def _create_completion(
        self,
        *,
        messages: List[Dict[str, str]],
        temperature: Optional[float],
        max_tokens: Optional[int],
        response_format: Optional[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> Any:
        """Send one raw Chat Completions request through the compatibility layer."""

        return create_chat_completion(
            self.client,
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = 2000,
        response_format: Optional[Dict] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
    ) -> str:
        """
        发送聊天请求
        
        Args:
            messages: 消息列表
            temperature: 温度参数
            max_tokens: 最大token数
            response_format: 响应格式（如JSON模式）
            tools: 可用工具列表
            tool_choice: 工具选择策略
            
        Returns:
            模型响应文本
        """
        response = self._create_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )
        content = extract_chat_completion_text(response)
        return _clean_chat_text(content)
    
    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: Optional[int] = 4096,
        max_attempts: int = 1,
    ) -> Dict[str, Any]:
        """Solicita respuesta JSON al LLM con negociación de capacidades y reintentos."""
        return execute_chat_json_with_retries(
            lambda msgs, cap, rf: self._create_completion(
                messages=msgs,
                temperature=temperature,
                max_tokens=cap,
                response_format=rf,
            ),
            extract_chat_completion_text,
            messages=messages,
            max_tokens=max_tokens,
            max_attempts=max_attempts,
            repair_on_final=False,
        )

    @staticmethod
    def _parse_json_response(response: Any) -> Dict[str, Any]:
        choices = getattr(response, "choices", None) or []
        choice = choices[0] if choices else None
        finish_reason = getattr(choice, "finish_reason", None) if choice is not None else None
        raw_text = extract_chat_completion_text(response) if choices else ""
        return parse_json_completion(
            raw_text,
            finish_reason=finish_reason,
            has_choices=bool(choices),
            allow_repair_on_length=False,
        )
