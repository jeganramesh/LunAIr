import pytest

from lunair.api.routes.chat import extract_provider, summarize_error
from lunair.services.retention_service import _partition_start


@pytest.mark.parametrize(
    "model,expected",
    [
        ("gpt-4o-mini", "openai"),
        ("gemini-2.0-flash", "gemini"),
        ("groq-llama", "groq"),
        ("llama-3.3-70b", "groq"),
    ],
)
def test_extract_provider(model, expected):
    assert extract_provider(model) == expected


def test_extract_provider_defaults_to_openai():
    assert extract_provider("some-unknown-model") == "openai"


def test_summarize_error_handles_none():
    assert "no provider attempted" in summarize_error(None)


def test_summarize_error_collapses_whitespace():
    assert summarize_error(ValueError("a\n  b\tc")) == "a b c"


def test_summarize_error_truncates():
    summary = summarize_error(ValueError("x" * 1000), limit=50)
    assert len(summary) <= 53
    assert summary.endswith("...")


@pytest.mark.parametrize(
    "bounds,expected",
    [
        ("FOR VALUES FROM ('2026-10-01 00:00:00+00') TO ('2026-11-01 00:00:00+00')", "2026-10-01"),
        ("FOR VALUES FROM ('2026-01-01 00:00:00+00') TO ('2026-02-01 00:00:00+00')", "2026-01-01"),
        ("DEFAULT", None),
        ("", None),
    ],
)
def test_partition_start_parsing(bounds, expected):
    result = _partition_start(bounds)
    if expected is None:
        assert result is None
    else:
        assert result is not None
        assert result.strftime("%Y-%m-%d") == expected