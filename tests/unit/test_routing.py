import pytest

from lunair.core.registry import ModelRegistry
from lunair.core.routing import (
    ProviderPreferences,
    apply_preferences,
    order_endpoints,
    reset,
    resolve_alias,
    select_endpoints,
)
from lunair.reliability import stats


@pytest.fixture(autouse=True)
def _clean():
    reset()
    stats.reset()
    yield
    reset()
    stats.reset()


def _registry() -> ModelRegistry:
    return ModelRegistry.from_config(
        {
            "models": {
                "chat": {
                    "endpoints": [
                        {"provider": "openai", "model": "openai/gpt-4o-mini", "price_in": 0.15, "price_out": 0.60},
                        {"provider": "gemini", "model": "gemini/gemini-2.0-flash", "price_in": 0.10, "price_out": 0.40},
                        {"provider": "groq", "model": "groq/llama-3.3-70b", "price_in": 0.05, "price_out": 0.08},
                    ]
                }
            }
        }
    )


def test_registry_parses_endpoints_and_deployments():
    reg = _registry()
    endpoints = reg.endpoints_for("chat")
    assert len(endpoints) == 3
    assert {e.provider for e in endpoints} == {"openai", "gemini", "groq"}
    # Multiple endpoints for one model get unique deployment names.
    assert len(set(e.deployment_name for e in endpoints)) == 3
    assert reg.get_endpoint(endpoints[0].deployment_name) == endpoints[0]


def test_registry_legacy_model_list():
    reg = ModelRegistry.from_config(
        {"model_list": [{"model_name": "gpt-4o-mini", "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": "k"}}]}
    )
    endpoints = reg.endpoints_for("gpt-4o-mini")
    assert len(endpoints) == 1
    assert endpoints[0].deployment_name == "gpt-4o-mini"
    assert reg.litellm_model_list()[0]["model_name"] == "gpt-4o-mini"


def test_resolve_alias_dict_and_legacy():
    cfg = {"aliases": {"auto/cheap": {"strategy": "cost_optimized", "candidates": ["a", "b"]}}, "auto/fast": ["c"]}
    assert resolve_alias("auto/cheap", cfg) == (["a", "b"], "cost_optimized", True)
    assert resolve_alias("auto/fast", cfg) == (["c"], None, True)
    assert resolve_alias("plain-model", cfg) == (["plain-model"], None, False)


def test_apply_preferences_only_ignore_zdr():
    endpoints = _registry().endpoints_for("chat")
    only, err = apply_preferences(endpoints, ProviderPreferences(only=["openai"]))
    assert err is None and [e.provider for e in only] == ["openai"]

    ignored, _ = apply_preferences(endpoints, ProviderPreferences(ignore=["openai"]))
    assert "openai" not in {e.provider for e in ignored}

    # No endpoint is ZDR in this fixture, so the request must be refused.
    _, err = apply_preferences(endpoints, ProviderPreferences(zdr=True))
    assert err is not None


def test_apply_preferences_max_price():
    endpoints = _registry().endpoints_for("chat")
    affordable, err = apply_preferences(endpoints, ProviderPreferences(max_price=0.5))
    assert err is None
    assert {e.provider for e in affordable} == {"gemini", "groq"}  # 0.50 and 0.13 blended

    _, err = apply_preferences(endpoints, ProviderPreferences(max_price=0.01))
    assert err is not None


def test_order_cost_optimized_cheapest_first():
    endpoints = _registry().endpoints_for("chat")
    ordered = order_endpoints(endpoints, "cost_optimized")
    assert [e.provider for e in ordered] == ["groq", "gemini", "openai"]


def test_order_round_robin_rotates():
    endpoints = _registry().endpoints_for("chat")
    first = [e.provider for e in order_endpoints(endpoints, "round_robin", model_id="chat")]
    second = [e.provider for e in order_endpoints(endpoints, "round_robin", model_id="chat")]
    assert first != second


def test_order_latency_optimized_uses_stats():
    endpoints = _registry().endpoints_for("chat")
    names = {e.provider: e.deployment_name for e in endpoints}
    stats.record_success(names["groq"], 5000.0)
    stats.record_success(names["gemini"], 100.0)
    stats.record_success(names["openai"], 900.0)
    ordered = order_endpoints(endpoints, "latency_optimized")
    assert ordered[0].provider == "gemini"


def test_select_endpoints_auto_alias():
    routing_cfg = {"strategy": "priority", "aliases": {"auto/cheap": {"strategy": "cost_optimized", "candidates": ["chat"]}}}
    endpoints, strategy, err = select_endpoints(
        "auto/cheap", registry=_registry(), routing_cfg=routing_cfg, prefs=ProviderPreferences()
    )
    assert err is None
    assert strategy == "cost_optimized"
    assert endpoints[0].provider == "groq"


def test_select_endpoints_unknown_model_errors():
    endpoints, _, err = select_endpoints(
        "nope", registry=_registry(), routing_cfg={}, prefs=ProviderPreferences()
    )
    assert endpoints == [] and err is not None
