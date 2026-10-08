import pytest
from lunair.core.router_engine import resolve_intent


def test_resolve_intent_auto_cheap():
    routing = {
        "auto/cheap": ["gemini-2.0-flash", "gpt-4o-mini"],
        "auto/fast": ["groq-llama", "gemini-2.0-flash"],
    }
    candidates = resolve_intent("auto/cheap", routing_config=routing)
    assert candidates == ["gemini-2.0-flash", "gpt-4o-mini"]


def test_resolve_intent_auto_fast():
    routing = {
        "auto/cheap": ["gemini-2.0-flash", "gpt-4o-mini"],
        "auto/fast": ["groq-llama", "gemini-2.0-flash"],
    }
    candidates = resolve_intent("auto/fast", routing_config=routing)
    assert candidates == ["groq-llama", "gemini-2.0-flash"]


def test_resolve_intent_passthrough():
    routing = {
        "auto/cheap": ["gemini-2.0-flash", "gpt-4o-mini"],
    }
    candidates = resolve_intent("gpt-4o-mini", routing_config=routing)
    assert candidates == ["gpt-4o-mini"]


def test_resolve_intent_unknown_auto():
    routing = {
        "auto/cheap": ["gemini-2.0-flash"],
    }
    candidates = resolve_intent("auto/smart", routing_config=routing)
    assert candidates == ["auto/smart"]
