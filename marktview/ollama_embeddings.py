"""Helpers to create embeddings for listings via a local Ollama instance."""

from __future__ import annotations

import logging
from typing import Iterable, List

import requests

from .models import Listing

DEFAULT_MODEL = "qwen3-embedding:0.6b"
DEFAULT_ENDPOINT = "http://localhost:11434/api/embeddings"
DEFAULT_TIMEOUT = 15.0

logger = logging.getLogger(__name__)


class OllamaEmbeddingError(RuntimeError):
    """Raised when the Ollama API does not return an embedding."""


def build_prompt(listing: Listing, *, max_chars: int = 1500) -> str:
    """Build a concise prompt for the embedding request.

    Parameters
    ----------
    listing:
        Listing object with title/body and metadata.
    max_chars:
        Hard limit for the prompt length to avoid very long payloads.

    Returns
    -------
    str
        The prompt that will be sent to the embedding endpoint.
    """

    parts: List[str] = [listing.title]

    if listing.body:
        parts.append(listing.body)

    metadata: List[str] = []
    if listing.postal_code:
        metadata.append(f"PLZ: {listing.postal_code}")
    if listing.created_at:
        metadata.append(f"Erstellt: {listing.created_at}")
    if listing.username:
        metadata.append(f"Nutzer: {listing.username}")

    if metadata:
        parts.append(" | ".join(metadata))

    prompt = "\n\n".join(part.strip() for part in parts if part.strip())
    if max_chars and len(prompt) > max_chars:
        prompt = prompt[: max_chars - 1].rstrip() + "…"

    return prompt


def embed_text(
    text: str,
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
) -> List[float]:
    """Create an embedding for a plain text snippet via Ollama."""

    response = requests.post(
        endpoint,
        json={"model": model, "prompt": text},
        timeout=timeout,
    )
    response.raise_for_status()

    data = response.json()
    embedding = data.get("embedding")
    if not embedding:
        raise OllamaEmbeddingError("Antwort enthält kein Embedding.")

    return embedding


def embed_listing(
    listing: Listing,
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
    max_chars: int = 1500,
) -> List[float]:
    """Create an embedding for a single listing object."""

    prompt = build_prompt(listing, max_chars=max_chars)
    if not prompt:
        raise OllamaEmbeddingError("Listing hat keinen Text für ein Embedding.")

    identifier = listing.listing_id or listing.title
    logger.info("Erzeuge Embedding für Anzeige: %s", identifier)

    return embed_text(
        prompt,
        model=model,
        endpoint=endpoint,
        timeout=timeout,
    )


def embed_listings(
    listings: Iterable[Listing],
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
    max_chars: int = 1500,
) -> List[tuple[Listing, List[float]]]:
    """Embed multiple listings sequentially.

    Returns a list of tuples ``(listing, embedding)`` so callers can
    persist both the original data and the resulting vector.
    """

    embedded: List[tuple[Listing, List[float]]] = []
    for listing in listings:
        embedding = embed_listing(
            listing,
            model=model,
            endpoint=endpoint,
            timeout=timeout,
            max_chars=max_chars,
        )
        embedded.append((listing, embedding))

    return embedded
