from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@patch("app.main.is_valid_twilio_request", return_value=True)
@patch("app.main.classify_intent", return_value="PREGUNTA")
@patch("app.main.answer_question", return_value="Respuesta de prueba")
def test_webhook_replies_with_twiml(mock_answer, mock_intent, mock_valid) -> None:
    response = client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp:+595981000000", "Body": "Hola"},
        headers={"X-Twilio-Signature": "fake"},
    )
    assert response.status_code == 200
    assert "Respuesta de prueba" in response.text
    assert response.headers["content-type"].startswith("application/xml")


@patch("app.main.is_valid_twilio_request", return_value=False)
def test_webhook_rejects_invalid_signature(mock_valid) -> None:
    response = client.post(
        "/webhook/whatsapp",
        data={"From": "whatsapp:+595981000000", "Body": "Hola"},
        headers={"X-Twilio-Signature": "invalid"},
    )
    assert response.status_code == 403