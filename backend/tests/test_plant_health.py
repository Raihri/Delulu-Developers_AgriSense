from __future__ import annotations

import base64
import io
import json

from fastapi.testclient import TestClient

import app as app_module
from app import app, require_plant_health
from config import GeminiSettings
from tools.plant_health import diagnose_plant_image


def _gemini_response(payload: dict) -> io.BytesIO:
    body = {
        "candidates": [
            {"content": {"parts": [{"text": json.dumps(payload)}]}}
        ]
    }
    return io.BytesIO(json.dumps(body).encode("utf-8"))


def test_gemini_proxy_uses_server_key_and_normalizes_top_diagnoses() -> None:
    captured: dict[str, object] = {}

    def opener(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return _gemini_response(
            {
                "status": "possible_issue",
                "plant_detected": True,
                "plant_confidence": 0.99,
                "healthy": False,
                "healthy_confidence": 0.12,
                "suggestions": [
                    {
                        "name": "Rust-like disease",
                        "scientific_name": "Puccinia species",
                        "common_names": ["crop rust"],
                        "confidence": 0.86,
                        "is_harmful": True,
                        "visible_evidence": "Orange pustule-like marks are visible.",
                        "prevention": "Keep tools clean and avoid wetting leaves.",
                        "field_check": "Check the underside for powdery orange spots.",
                    }
                ],
                "follow_up_question": "Are orange pustules visible underneath?",
            }
        )

    result = diagnose_plant_image(
        b"fake-jpeg-content",
        mime_type="image/jpeg",
        language="bn",
        symptom_notes="পাতার নিচে কমলা দাগ আছে",
        settings=GeminiSettings(api_key="secret-gemini-key", model="gemini-test"),
        opener=opener,
    )

    request = captured["request"]
    assert request.get_header("X-goog-api-key") == "secret-gemini-key"
    assert "secret-gemini-key" not in request.full_url
    assert request.full_url.endswith("/gemini-test:generateContent")
    sent = json.loads(request.data)
    inline_image = sent["contents"][0]["parts"][0]["inline_data"]
    assert inline_image["mime_type"] == "image/jpeg"
    assert inline_image["data"] == base64.b64encode(b"fake-jpeg-content").decode()
    prompt = sent["contents"][0]["parts"][1]["text"]
    assert "Bangla (Bengali)" in prompt
    assert "পাতার নিচে কমলা দাগ আছে" in prompt
    assert sent["generationConfig"]["responseMimeType"] == "application/json"
    assert "responseJsonSchema" in sent["generationConfig"]
    assert result["provider"] == "google_gemini_gemini-test"
    assert result["status"] == "possible_issue"
    assert result["suggestions"][0]["name"] == "Rust-like disease"
    assert result["suggestions"][0]["confidence"] == 0.86
    assert result["suggestions"][0]["chemical_guidance_withheld"] is True
    assert result["suggestions"][0]["source_url"] is None
    assert result["language"] == "bn"
    assert "পরীক্ষাগারে" in result["safety"]


def test_plant_health_endpoint_validates_image_and_never_needs_supabase(monkeypatch) -> None:
    settings = GeminiSettings(api_key="server-only-key", model="gemini-test")
    app.dependency_overrides[require_plant_health] = lambda: settings
    monkeypatch.setattr(
        app_module,
        "diagnose_plant_image",
        lambda image, *, mime_type, language, symptom_notes, settings: {
            "status": "healthy",
            "received_bytes": len(image),
            "received_mime_type": mime_type,
            "received_language": language,
            "received_notes": symptom_notes,
            "provider": "google_gemini_gemini-test",
        },
    )
    try:
        client = TestClient(app)
        image = b"\xff\xd8\xff" + b"0" * 40
        response = client.post(
            "/plant-health/diagnose",
            json={
                "image_base64": base64.b64encode(image).decode(),
                "mime_type": "image/jpeg",
                "filename": "leaf.jpg",
                "language": "bn",
                "symptom_notes": "দুই দিন ধরে দাগ",
            },
        )
        assert response.status_code == 200
        assert response.json()["received_bytes"] == len(image)
        assert response.json()["received_mime_type"] == "image/jpeg"
        assert response.json()["received_language"] == "bn"
        assert response.json()["received_notes"] == "দুই দিন ধরে দাগ"

        invalid = client.post(
            "/plant-health/diagnose",
            json={
                "image_base64": base64.b64encode(b"not-an-image" * 4).decode(),
                "mime_type": "image/jpeg",
            },
        )
        assert invalid.status_code == 415
    finally:
        app.dependency_overrides.clear()


def test_plant_health_endpoint_fails_clearly_without_gemini_key() -> None:
    app.dependency_overrides[require_plant_health] = lambda: None
    try:
        client = TestClient(app)
        image = b"\x89PNG\r\n\x1a\n" + b"0" * 40
        response = client.post(
            "/plant-health/diagnose",
            json={
                "image_base64": base64.b64encode(image).decode(),
                "mime_type": "image/png",
            },
        )
        assert response.status_code == 503
        assert "GEMINI_API_KEY" in response.json()["detail"]
    finally:
        app.dependency_overrides.clear()
