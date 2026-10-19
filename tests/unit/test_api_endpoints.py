from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from lunair.config import settings
from lunair.main import app

client = TestClient(app)

GATEWAY_SECRET = "test-secret"


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
    """Pretend every provider has a real key so the preflight check passes.

    Patched on the class, not the instance: pydantic-settings models reject
    attribute assignment on instances.
    """
    with patch(
        "lunair.config.Settings.get_unconfigured_providers",
        return_value={},
    ):
        yield


@pytest.fixture
def gateway_trust():
    """Configure a shared secret and return the headers the gateway would send."""
    with patch.object(settings, "gateway_shared_secret", GATEWAY_SECRET):
        yield {"X-LUNAIR-Verified": "true", "X-LUNAIR-Key-Id": "key_test_123",
               "X-LUNAIR-Gateway-Secret": GATEWAY_SECRET}


def test_models_endpoint():
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    model_ids = [m["id"] for m in data["data"]]
    # Should include models configured in config.yaml and auto/* pseudo-models
    assert "gpt-4o-mini" in model_ids
    assert "gemini-2.0-flash" in model_ids
    assert "groq-llama" in model_ids
    assert "auto/cheap" in model_ids
    assert "auto/fast" in model_ids


def test_chat_completions_with_trusted_header(providers_configured, gateway_trust):
    mock_response = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello from mock!"},
                "finish_reason": "stop",
            }
        ],
        "model": "gemini-2.0-flash",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    with patch("lunair.core.litellm_router.router.acompletion", new=AsyncMock(return_value=mock_response)):
        payload = {
            "model": "auto/cheap",
            "messages": [{"role": "user", "content": "Hello!"}],
        }
        resp = client.post("/v1/chat/completions", json=payload, headers=gateway_trust)
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello from mock!"
        assert resp.headers.get("X-LUNAIR-Provider") == "gemini"
        assert resp.headers.get("X-LUNAIR-Model") == "gemini-2.0-flash"
        assert "X-LUNAIR-Cost-USD" in resp.headers


def test_chat_completions_with_bearer_token(providers_configured):
    """Direct callers authenticate with a Bearer key (dev bypass enabled here)."""
    mock_response = {
        "id": "chatcmpl-test-bearer",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello via direct bearer!"},
                "finish_reason": "stop",
            }
        ],
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 8, "completion_tokens": 4, "total_tokens": 12},
    }

    with patch("lunair.core.litellm_router.router.acompletion", new=AsyncMock(return_value=mock_response)), \
         patch.object(settings, "dev_auth_bypass", True):
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hello!"}],
        }
        headers = {"Authorization": "Bearer sk-test-key-123456"}
        resp = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert resp.status_code == 200
        assert resp.headers.get("X-LUNAIR-Provider") == "openai"
        assert resp.headers.get("X-LUNAIR-Model") == "gpt-4o-mini"


def test_chat_completions_without_provider_credentials_returns_503(gateway_trust):
    """Placeholder keys must fail fast with an actionable message."""
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hello!"}],
    }

    with patch(
        "lunair.config.Settings.get_unconfigured_providers",
        return_value={"openai": "OPENAI_API_KEY"},
    ):
        resp = client.post("/v1/chat/completions", json=payload, headers=gateway_trust)

    assert resp.status_code == 503
    assert "OPENAI_API_KEY" in resp.json()["detail"]


def test_chat_completions_missing_auth_fails():
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hello!"}],
    }
    # No X-LUNAIR-Verified and no Authorization header
    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 401
