import pytest
from lunair.reliability import circuit_breaker


@pytest.fixture(autouse=True)
def clean_breakers():
    circuit_breaker.reset()
    yield
    circuit_breaker.reset()


def test_unknown_provider_is_closed():
    state = circuit_breaker.get_state("openai")
    assert state["state"] == "closed"
    assert state["consecutive_failures"] == 0
    assert state["total_failures"] == 0
    assert state["last_failure_at"] is None


def test_failures_below_threshold_stay_closed():
    circuit_breaker.record_failure("openai")
    circuit_breaker.record_failure("openai")
    state = circuit_breaker.get_state("openai")
    assert state["state"] == "closed"
    assert state["consecutive_failures"] == 2


def test_threshold_opens_circuit():
    for _ in range(3):
        circuit_breaker.record_failure("openai")
    state = circuit_breaker.get_state("openai")
    assert state["state"] == "open"
    assert state["consecutive_failures"] == 3
    assert state["total_failures"] == 3
    assert state["last_failure_at"] is not None


def test_cooldown_moves_to_half_open():
    for _ in range(3):
        circuit_breaker.record_failure("openai")
    # cooldown of 0s means the window has already elapsed
    state = circuit_breaker.get_state("openai", cooldown_seconds=0)
    assert state["state"] == "half_open"


def test_success_resets_failures():
    circuit_breaker.record_failure("openai")
    circuit_breaker.record_failure("openai")
    circuit_breaker.record_success("openai")
    state = circuit_breaker.get_state("openai")
    assert state["state"] == "closed"
    assert state["consecutive_failures"] == 0


def test_success_closes_an_open_circuit():
    for _ in range(5):
        circuit_breaker.record_failure("groq")
    assert circuit_breaker.get_state("groq")["state"] == "open"
    circuit_breaker.record_success("groq")
    assert circuit_breaker.get_state("groq")["state"] == "closed"


def test_providers_are_isolated():
    for _ in range(3):
        circuit_breaker.record_failure("openai")
    assert circuit_breaker.get_state("openai")["state"] == "open"
    assert circuit_breaker.get_state("gemini")["state"] == "closed"
    assert circuit_breaker.get_state("groq")["state"] == "closed"


def test_circuit_states_covers_configured_providers():
    states = circuit_breaker.get_circuit_states()
    assert {"openai", "gemini", "groq"} <= set(states)
    for info in states.values():
        assert info["state"] in {"closed", "open", "half_open"}