import pytest

from marktview import ollama_embeddings as oe
from marktview.models import Listing


class DummyResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_build_prompt_truncates_and_collects_metadata():
    listing = Listing(
        title="Titel",
        url="https://example.com",
        body="Text" * 600,
        postal_code="12345",
        created_at="Heute",
        username="User",
    )
    prompt = oe.build_prompt(listing, max_chars=20)
    assert prompt.endswith("…")
    assert len(prompt) <= 20


def test_embed_text_and_listing(monkeypatch):
    calls = {}

    def fake_post(endpoint, json, timeout):  # noqa: A002
        calls["endpoint"] = endpoint
        calls["json"] = json
        calls["timeout"] = timeout
        return DummyResponse({"embedding": [0.1, 0.2]})

    monkeypatch.setattr(oe.requests, "post", fake_post)
    vector = oe.embed_text("hello", model="m", endpoint="http://e", timeout=1.0)
    assert vector == [0.1, 0.2]
    assert calls == {"endpoint": "http://e", "json": {"model": "m", "prompt": "hello"}, "timeout": 1.0}

    listing = Listing(title="Titel", url="https://example.com", body="Text")
    vector_listing = oe.embed_listing(listing, model="m", endpoint="http://e")
    assert vector_listing == [0.1, 0.2]

    embedded = oe.embed_listings([listing], model="m", endpoint="http://e")
    assert embedded == [(listing, [0.1, 0.2])]


def test_embed_listing_without_prompt(monkeypatch):
    listing = Listing(title="", url="https://example.com", body="")
    monkeypatch.setattr(oe, "build_prompt", lambda *_args, **_kwargs: "")
    with pytest.raises(oe.OllamaEmbeddingError):
        oe.embed_listing(listing)


def test_embed_text_raises_for_missing_embedding(monkeypatch):
    monkeypatch.setattr(oe.requests, "post", lambda *_args, **_kwargs: DummyResponse({}))
    with pytest.raises(oe.OllamaEmbeddingError):
        oe.embed_text("text")
