from unittest.mock import patch
from litellm import AuthenticationError
from lunair.core.litellm_router import create_router


def test_router_creation():
    model_list = [
        {"model_name": "gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "test-key"}},
        {"model_name": "gemini-2.0-flash", "litellm_params": {"model": "gemini/gemini-2.0-flash", "api_key": "test-key"}},
    ]
    fallbacks = [{"gpt-4o-mini": ["gemini-2.0-flash"]}]
    r = create_router(model_list=model_list, fallbacks=fallbacks)
    assert len(r.model_list) == 2


def test_router_completion_success(monkeypatch):
    model_list = [
        {"model_name": "gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "test-key"}},
    ]
    r = create_router(model_list=model_list, fallbacks=[])

    mock_response = {
        "id": "chatcmpl-test",
        "choices": [{"message": {"role": "assistant", "content": "Hello!"}}],
        "model": "gpt-4o-mini",
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }

    with patch("litellm.router.litellm.completion", return_value=mock_response):
        resp = r.completion(model="gpt-4o-mini", messages=[{"role": "user", "content": "Hi"}])
        assert resp["choices"][0]["message"]["content"] == "Hello!"


def test_router_fallback_on_primary_failure():
    model_list = [
        {"model_name": "gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "bad-key"}},
        {"model_name": "gemini-2.0-flash", "litellm_params": {"model": "gemini/gemini-2.0-flash", "api_key": "good-key"}},
    ]
    fallbacks = [{"gpt-4o-mini": ["gemini-2.0-flash"]}]
    r = create_router(model_list=model_list, fallbacks=fallbacks, num_retries=1)

    def mock_completion(**kwargs):
        model = kwargs.get("model")
        if "openai" in model or "gpt-4o-mini" in model:
            raise AuthenticationError(
                message="Invalid OpenAI API key",
                llm_provider="openai",
                model="gpt-4o-mini",
            )
        return {
            "id": "chatcmpl-gemini",
            "choices": [{"message": {"role": "assistant", "content": "Response from Gemini fallback"}}],
            "model": "gemini-2.0-flash",
            "usage": {"prompt_tokens": 5, "completion_tokens": 5, "total_tokens": 10},
        }

    with patch("litellm.router.litellm.completion", side_effect=mock_completion):
        resp = r.completion(model="gpt-4o-mini", messages=[{"role": "user", "content": "Hi"}])
        assert resp["choices"][0]["message"]["content"] == "Response from Gemini fallback"
        assert resp["model"] == "gemini-2.0-flash"
