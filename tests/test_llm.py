import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from marktview import llm
from marktview.models import Listing


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def raise_for_status(self):
        if not (200 <= self.status_code < 400):
            raise requests.exceptions.HTTPError(response=self)

    def json(self):
        return self._payload


class FakeService(llm._LocalOllamaService):
    def __init__(self):
        super().__init__()
        self.started = False

    def ensure_running(self, *, model, endpoint):  # noqa: ARG002
        self.started = True

    def stop(self):
        self.started = False


def test_build_gender_prompt_and_normalization():
    listing = Listing(title="Titel", url="https://example.com", body="Body", username="User")
    prompt = llm._build_gender_prompt(listing)
    assert "Titel" in prompt and "Body" in prompt and "User" in prompt

    normalized = llm._normalize_gender_output("Weiblich 80%")
    assert normalized == "weiblich 80%"

    normalized_missing_percent = llm._normalize_gender_output("Divers")
    assert normalized_missing_percent == "divers 50%"

    with pytest.raises(llm.LLMInferenceError):
        llm._normalize_gender_output("keine Angabe")


def test_build_target_audience_prompt_and_normalization():
    listing = Listing(title="Titel", url="https://example.com", body="Body")
    prompt = llm._build_target_audience_prompt(listing)
    assert "Zielgruppe" in prompt

    assert llm._normalize_target_audience_output("Für Frauen") == "weiblich"
    assert llm._normalize_target_audience_output("Bi und alle") == "bi"

    listing_with_user = Listing(title="Titel", url="https://example.com", username="User")
    prompt_user = llm._build_target_audience_prompt(listing_with_user)
    assert "Nutzername" in prompt_user

    with pytest.raises(llm.LLMInferenceError):
        llm._normalize_target_audience_output("ohne Hinweis")


def test_llm_logging_config(tmp_path: Path):
    log_dir = tmp_path / "logs"
    llm.configure_llm_logging(log_dir)
    llm.configure_llm_logging(log_dir)
    assert (log_dir / "llm.log").exists()


def test_llm_client_success(monkeypatch):
    listing = Listing(title="Titel", url="https://example.com")
    service = FakeService()

    def fake_post(endpoint, json, timeout):  # noqa: A002
        assert endpoint == llm.DEFAULT_ENDPOINT
        assert json["model"] == llm.DEFAULT_MODEL
        return DummyResponse({"response": "weiblich 90%"})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    client = llm.LLMClient(service=service)
    result = client.infer_gender_for_listing(listing)
    assert service.started is True
    assert result == "weiblich 90%"


def test_llm_client_retry_and_fallback(monkeypatch):
    listing = Listing(title="Titel", url="https://example.com")

    attempts = {"count": 0}

    def fake_post(endpoint, json, timeout):  # noqa: A002
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise requests.exceptions.RequestException("network down")
        return DummyResponse({"response": "unbekannt 10%"})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    client = llm.LLMClient(service=FakeService())
    result = client.query("prompt")
    assert attempts["count"] == 10
    assert result == "unbekannt 10%"


def test_llm_client_http_error(monkeypatch):
    listing = Listing(title="Titel", url="https://example.com")

    def fake_post(endpoint, json, timeout):  # noqa: A002
        return DummyResponse({"error": "missing"}, status_code=500)

    monkeypatch.setattr(llm.requests, "post", fake_post)
    client = llm.LLMClient(service=FakeService())
    with pytest.raises(llm.LLMInferenceError):
        client.infer_gender_for_listing(listing)


def test_llm_client_custom_endpoint(monkeypatch):
    listing = Listing(title="Titel", url="https://example.com")
    service = FakeService()

    def fake_post(endpoint, json, timeout):  # noqa: A002
        assert endpoint == "http://remote/api/generate"
        return DummyResponse({"response": "männlich 99%"})

    monkeypatch.setattr(llm.requests, "post", fake_post)
    client = llm.LLMClient(
        model="custom-model",
        endpoint="http://remote/api/generate",
        timeout=1.0,
        service=service,
    )
    result = client.infer_target_audience_for_listing(listing)
    assert result == "männlich"
    assert service.started is False


def test_default_client_wrappers(monkeypatch):
    listing = Listing(title="Titel", url="https://example.com")
    called = {}

    monkeypatch.setattr(llm, "_default_client", SimpleNamespace(
        infer_gender_for_listing=lambda l: called.setdefault("gender", l.title),
        infer_target_audience_for_listing=lambda l: called.setdefault("audience", l.url),
    ))

    assert llm.infer_gender_for_listing(listing) == "Titel"
    assert llm.infer_target_audience_for_listing(listing) == "https://example.com"


def test_local_service_helpers(monkeypatch):
    service = llm._LocalOllamaService()
    monkeypatch.setattr(llm.requests, "get", lambda *_args, **_kwargs: DummyResponse({"models": []}))
    assert service._base_url("http://localhost:11434/api/generate") == "http://localhost:11434"
    assert service._model_exists("http://localhost:11434", "gemma3:4b") is False

    called = {}

    def fake_run(cmd, stdout=None, stderr=None, check=None, text=None, env=None):  # noqa: ARG002
        called["cmd"] = cmd
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(llm.subprocess, "run", fake_run)
    monkeypatch.setattr(service, "_wait_until_ready", lambda *_: None)
    service._pull_model("ollama", "gemma3:4b")
    assert called["cmd"][1:] == ["pull", "gemma3:4b"]
