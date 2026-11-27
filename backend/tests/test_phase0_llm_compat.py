"""Pruebas de Fase 0: Capa LLM Unificada, TokenBudgetManager y CamelGatewayModel."""

from types import SimpleNamespace
import pytest

from app.llm.camel_adapter import CamelGatewayModel
from app.llm.gateway import UnifiedLLMGateway, create_chat_completion
from app.llm.token_budget import BudgetProfiles, TokenBudgetManager


class HttpError413(RuntimeError):
    def __init__(self, msg="413 Payload Too Large"):
        super().__init__(msg)
        self.status_code = 413
        self.body = {"error": {"message": msg, "code": "payload_too_large"}}


class HttpTransientError(RuntimeError):
    def __init__(self, status_code, msg):
        super().__init__(msg)
        self.status_code = status_code
        self.body = {"error": {"message": msg}}


def _ok_response(text='{"ok": true}'):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=text),
            )
        ]
    )


def test_token_budget_shrinks_on_413_and_recovers():
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise HttpError413("Error code: 413 - Request entity too large")
            return _ok_response("Respuesta recuperada")

    client = SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions()))
    long_msgs = [
        {"role": "system", "content": "Sistema breve"},
        {"role": "user", "content": "x" * 2000},
        {"role": "assistant", "content": "y" * 2000},
        {"role": "user", "content": "Pregunta final importante"},
    ]

    res = create_chat_completion(
        client,
        model="auto",
        messages=long_msgs,
        max_tokens=2000,
        max_retries=3,
        sleep_fn=lambda _s: None,
    )

    assert len(calls) == 2
    assert calls[1]["max_tokens"] == 1400  # int(2000 * 0.70)
    assert TokenBudgetManager.estimate_messages_tokens(calls[1]["messages"]) < TokenBudgetManager.estimate_messages_tokens(long_msgs)
    assert res.choices[0].message.content == "Respuesta recuperada"


@pytest.mark.parametrize("code", [429, 502, 503])
def test_gateway_retries_transient_http_errors(code):
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if len(calls) < 2:
                raise HttpTransientError(code, f"Error code: {code} upstream_failed")
            return _ok_response('{"status": "recovered"}')

    gateway = UnifiedLLMGateway(
        api_key="test-key",
        base_url="http://127.0.0.1:3001/v1",
        model="auto",
        client=SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )

    out = gateway.chat_json(
        messages=[{"role": "user", "content": "Devuelve JSON"}],
        max_tokens=1000,
        max_attempts=2,
    )
    assert out == {"status": "recovered"}
    assert len(calls) == 2


def test_auto_model_omits_response_format_in_gateway():
    calls = []

    class FakeCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return _ok_response('{"ok": true}')

    gateway = UnifiedLLMGateway(
        api_key="test-key",
        base_url="http://127.0.0.1:3001/v1",
        model="auto",
        client=SimpleNamespace(chat=SimpleNamespace(completions=FakeCompletions())),
    )

    res = gateway.chat_json(messages=[{"role": "user", "content": "JSON"}], max_attempts=1)
    assert res == {"ok": True}
    assert "response_format" not in calls[0]


def test_camel_gateway_model_fits_simulation_budget():
    model = CamelGatewayModel(
        model_type="auto",
        api_key="test-key",
        url="http://127.0.0.1:3001/v1",
    )
    huge_messages = [
        {"role": "system", "content": "Eres un ciudadano de prueba."},
        {"role": "user", "content": "contexto " * 3000},
        {"role": "user", "content": "Pregunta concreta"},
    ]
    fitted, params = model._prepare_gateway_args(huge_messages)
    assert TokenBudgetManager.estimate_messages_tokens(fitted) <= BudgetProfiles.SIMULATION_TURN.max_input_tokens + 250
    assert fitted[-1]["content"] == "Pregunta concreta"
    assert isinstance(params, dict)
