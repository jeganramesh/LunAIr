from fastapi.testclient import TestClient
from lunair.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_echo_endpoint():
    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello!"},
        ],
        "temperature": 0.7,
        "max_tokens": 100,
    }
    response = client.post("/v1/echo", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "gpt-4o-mini"
    assert len(data["messages"]) == 2
    assert data["messages"][0]["role"] == "system"
    assert data["messages"][1]["content"] == "Hello!"
