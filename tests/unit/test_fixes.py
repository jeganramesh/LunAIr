from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from lunair.config import settings
from lunair.main import app
from lunair.reliability import circuit_breaker
from lunair.reliability.rate_limiter import estimate_tokens

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_limits_no_db():
    """Neutralise rate limiting and budget lookups for handler tests."""
    with patch("lunair.config.Settings.get_rate_limit_config", return_value={}), \
         patch("lunair.config.Settings.get_budget_config", return_value={"default_monthly_usd": 50}), \
         patch("lunair.api.routes.chat.limit_for_key", new=AsyncMock(return_value=None)), \
         patch("lunair.api.routes.chat.check_budget", new=AsyncMock()) as budget:
        budget.return_value.allowed = True
        yield


@pytest.fixture
def providers_configured():
    with patch("lunair.config.Settings.get_unconfigured_providers", return_value={}):
        yield


@pytest.fixture
def gateway_secret():
    with patch.object(settings, "gateway_shared_secret", "test-secret"):
        yield "test-secret"


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


def _ok_payload(model="gemini-2.0-flash"):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 1,
        "model": model,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


# --- trust boundary ---------------------------------------------------------

def test_gateway_header_without_secret_is_rejected(providers_configured, gateway_secret):
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        headers={"X-LUNAIR-Verified": "true", "X-LUNAIR-Key-Id": "spoofed"},
    )
    assert resp.status_code == 401


def test_gateway_header_with_wrong_secret_is_rejected(providers_configured, gateway_secret):
    resp = client.post(
        "/v1/chat/completions",
        json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
        headers={
            "X-LUNAIR-Verified": "true",
            "X-LUNAIR-Key-Id": "spoofed",
            "X-LUNAIR-Gateway-Secret": "wrong",
        },
    )
    assert resp.status_code == 401


def test_gateway_header_with_correct_secret_is_accepted(providers_configured, gateway_secret):
    with patch("lunair.core.litellm_router.router.acompletion", new=AsyncMock(return_value=_FakeResponse(_ok_payload()))):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={
                "X-LUNAIR-Verified": "true",
                "X-LUNAIR-Key-Id": "key_abc",
                "X-LUNAIR-Gateway-Secret": gateway_secret,
            },
        )
    assert resp.status_code == 200


def test_dev_bypass_off_rejects_unknown_bearer():
    with patch.object(settings, "dev_auth_bypass", False):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer sk-whatever"},
        )
    assert resp.status_code == 401


# --- fallback header semantics ---------------------------------------------

def test_auto_alias_success_has_no_fallback_header(providers_configured, gateway_secret):
    with patch("lunair.core.litellm_router.router.acompletion", new=AsyncMock(return_value=_FakeResponse(_ok_payload()))):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "auto/cheap", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-LUNAIR-Verified": "true", "X-LUNAIR-Key-Id": "k", "X-LUNAIR-Gateway-Secret": gateway_secret},
        )
    # auto/cheap is an alias expansion, not a failover.
    assert "X-LUNAIR-Fallback-From" not in resp.headers
    assert resp.headers["X-LUNAIR-Requested"] == "auto/cheap"
    assert resp.headers["X-LUNAIR-Model"] == "gemini-2.0-flash"


def test_real_failover_sets_fallback_header(providers_configured, gateway_secret):
    calls = {"n": 0}

    async def flaky(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("primary down")
        return _FakeResponse(_ok_payload(model="gpt-4o-mini"))

    with patch("lunair.core.litellm_router.router.acompletion", new=AsyncMock(side_effect=flaky)):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "auto/cheap", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-LUNAIR-Verified": "true", "X-LUNAIR-Key-Id": "k", "X-LUNAIR-Gateway-Secret": gateway_secret},
        )
    assert resp.status_code == 200
    assert resp.headers["X-LUNAIR-Fallback-From"] == "gemini-2.0-flash"
    assert resp.headers["X-LUNAIR-Model"] == "gpt-4o-mini"


# --- parameter forwarding ---------------------------------------------------

def test_build_upstream_kwargs_forwards_parameters():
    from lunair.api.routes.chat import build_upstream_kwargs
    from lunair.schemas.chat import ChatCompletionRequest

    req = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.3,
        top_p=0.9,
        n=2,
        max_tokens=64,
        seed=7,
    )
    kwargs = build_upstream_kwargs(req, "gpt-4o-mini", stream=False)
    assert kwargs["temperature"] == 0.3
    assert kwargs["top_p"] == 0.9
    assert kwargs["n"] == 2
    assert kwargs["max_tokens"] == 64
    assert kwargs["seed"] == 7


def test_build_upstream_kwargs_enables_stream_usage():
    from lunair.api.routes.chat import build_upstream_kwargs
    from lunair.schemas.chat import ChatCompletionRequest

    req = ChatCompletionRequest(model="gpt-4o-mini", messages=[{"role": "user", "content": "hi"}])
    kwargs = build_upstream_kwargs(req, "gpt-4o-mini", stream=True)
    assert kwargs["stream_options"]["include_usage"] is True


def test_multimodal_and_tool_messages_are_accepted():
    from lunair.schemas.chat import ChatCompletionRequest

    req = ChatCompletionRequest(
        model="gpt-4o-mini",
        messages=[
            {"role": "user", "content": [{"type": "text", "text": "what is this"}]},
            {"role": "assistant", "content": None, "tool_calls": [{"id": "1", "type": "function"}]},
            {"role": "tool", "content": "result", "tool_call_id": "1"},
        ],
    )
    assert len(req.messages) == 3
    assert req.messages[1].content is None
    assert req.messages[1].tool_calls[0]["id"] == "1"


# --- rate limiter / breaker helpers -----------------------------------------

def test_estimate_tokens_counts_text():
    assert estimate_tokens([{"role": "user", "content": "a" * 40}]) == 10
    assert estimate_tokens([{"role": "user", "content": [{"type": "text", "text": "b" * 8}]}]) == 2


def test_breaker_is_available_transitions():
    circuit_breaker.reset()
    assert circuit_breaker.is_available("openai") is True
    for _ in range(3):
        circuit_breaker.record_failure("openai")
    assert circuit_breaker.is_available("openai") is False
    # A zero cooldown means the probe window has already elapsed.
    assert circuit_breaker.is_available("openai", cooldown_seconds=0) is True
    circuit_breaker.reset()


# --- key management ---------------------------------------------------------

def test_keys_api_disabled_without_admin_key():
    with patch.object(settings, "admin_api_key", None):
        resp = client.get("/v1/keys")
    assert resp.status_code == 404


def test_keys_api_rejects_wrong_admin_key():
    with patch.object(settings, "admin_api_key", "admin-secret"):
        resp = client.get("/v1/keys", headers={"X-LUNAIR-Admin-Key": "nope"})
    assert resp.status_code == 401
