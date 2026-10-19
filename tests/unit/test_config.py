from lunair.config import is_usable_api_key, settings


def test_placeholder_keys_are_rejected():
    assert is_usable_api_key(None) is False
    assert is_usable_api_key("") is False
    assert is_usable_api_key("   ") is False
    assert is_usable_api_key("sk-REPLACE_ME") is False
    assert is_usable_api_key("REPLACE_ME") is False
    assert is_usable_api_key("CHANGE_ME") is False


def test_real_keys_are_accepted():
    assert is_usable_api_key("sk-abc123") is True
    assert is_usable_api_key("gsk_xyz789") is True


def test_provider_status_shape():
    status = settings.get_provider_status()
    assert set(status) >= {"openai", "gemini", "groq"}
    for provider, info in status.items():
        assert set(info) == {"configured", "env_var", "model"}
        assert isinstance(info["configured"], bool)
        assert info["env_var"].endswith("_API_KEY")
        assert info["model"].startswith(f"{provider}/")


def test_unconfigured_providers_match_status():
    status = settings.get_provider_status()
    unconfigured = settings.get_unconfigured_providers()

    for provider, info in status.items():
        if info["configured"]:
            assert provider not in unconfigured
        else:
            assert unconfigured[provider] == info["env_var"]


def test_unconfigured_consumes_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real-looking-value")
    monkeypatch.setenv("GEMINI_API_KEY", "REPLACE_ME")
    monkeypatch.setenv("GROQ_API_KEY", "")

    unconfigured = settings.get_unconfigured_providers()
    assert "openai" not in unconfigured
    assert unconfigured["gemini"] == "GEMINI_API_KEY"
    assert unconfigured["groq"] == "GROQ_API_KEY"