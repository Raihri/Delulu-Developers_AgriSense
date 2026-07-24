from __future__ import annotations

import io
import json
from urllib.error import HTTPError

import pytest

import intake.parser as parser
from config import GeminiSettings
from intake.parser import (
    GeminiIntakeExtractor,
    GeminiTransientError,
)
from tests.intake_fakes import empty_raw


def _gemini_response(payload: dict) -> io.BytesIO:
    body = {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(payload)}],
                }
            }
        ]
    }
    return io.BytesIO(json.dumps(body).encode())


def _http_503() -> HTTPError:
    return HTTPError(
        url="https://generativelanguage.googleapis.com/",
        code=503,
        msg="Service Unavailable",
        hdrs=None,
        fp=io.BytesIO(b'{"error":{"code":503}}'),
    )


def test_gemini_retries_transient_http_failure_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter([_http_503(), _gemini_response(empty_raw())])
    attempts = 0

    def fake_urlopen(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(parser, "urlopen", fake_urlopen)
    monkeypatch.setattr(parser.time, "sleep", lambda _seconds: None)
    extractor = GeminiIntakeExtractor(
        GeminiSettings(api_key="test-key", model="test-model")
    )

    result = extractor._generate("prompt", {})  # noqa: SLF001

    assert attempts == 2
    assert result == empty_raw()


def test_gemini_stops_after_three_transient_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0

    def fake_urlopen(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise _http_503()

    monkeypatch.setattr(parser, "urlopen", fake_urlopen)
    monkeypatch.setattr(parser.time, "sleep", lambda _seconds: None)
    extractor = GeminiIntakeExtractor(
        GeminiSettings(api_key="test-key", model="test-model")
    )

    with pytest.raises(GeminiTransientError, match="after 3 attempts"):
        extractor._generate("prompt", {})  # noqa: SLF001

    assert attempts == 3
