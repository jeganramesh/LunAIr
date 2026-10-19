from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient
from lunair.main import app

client = TestClient(app)


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


def test_chat_completions_with_trusted_header(providers_configured):
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
        headers = {
            "X-LUNAIR-Verified": "true",
            "X-LUNAIR-Key-Id": "key_test_123",
        }
        resp = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["choices"][0]["message"]["content"] == "Hello from mock!"
        assert resp.headers.get("X-LUNAIR-Provider") == "gemini"
        assert resp.headers.get("X-LUNAIR-Model") == "gemini-2.0-flash"
        assert "X-LUNAIR-Cost-USD" in resp.headers


def test_chat_completions_with_bearer_token(providers_configured):
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

    with patch("lunair.core.litellm_router.router.acompletion", new=AsyncMock(return_value=mock_response)):
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "Hello!"}],
        }
        headers = {
            "Authorization": "Bearer sk-test-key-123456",
        }
        resp = client.post("/v1/chat/completions", json=payload, headers=headers)
        assert resp.status_code == 200
        assert resp.headers.get("X-LUNAIR-Provider") == "openai"
        assert resp.headers.get("X-LUNAIR-Model") == "gpt-4o-mini"


def test_chat_completions_without_provider_credentials_returns_503():
    """Placeholder keys must fail fast with an actionable message."""
    payload = {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Hello!"}],
    }
    headers = {"X-LUNAIR-Verified": "true"}

    with patch(
        "lunair.config.Settings.get_unconfigured_providers",
        return_value={"openai": "OPENAI_API_KEY"},
    ):
        resp = client.post("/v1/chat/completions", json=payload, headers=headers)

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
