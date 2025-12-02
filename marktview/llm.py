"""LLM helpers for gender inference when listings omit that metadata."""

from __future__ import annotations

import logging
from typing import Optional

import requests

from .models import Listing

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "llama3.1:8b"
DEFAULT_ENDPOINT = "http://localhost:11434/api/generate"
DEFAULT_TIMEOUT = 30.0


class LLMInferenceError(RuntimeError):
    """Raised when the LLM endpoint cannot return a valid answer."""


def _build_gender_prompt(listing: Listing) -> str:
    """Construct the German prompt required for gender inference."""

    parts = ["Anzeigetext:"]
    if listing.title:
        parts.append(f"Titel: {listing.title}")
    if listing.body:
        parts.append(listing.body)
    if listing.username and listing.username != "nicht angegeben":
        parts.append(f"Nutzername: {listing.username}")
    question = (
        "Antworte nur mit dem Warscheinlichten geschlecht des Anzeigen Autors plus "
        "der Prozentualen Warscheinlichkeit wie sicher du bist das dieses Geschlecht "
        "stimmt"
    )
    parts.append(question)
    return "\n\n".join(part for part in parts if part)


def query_llm(
    prompt: str,
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Send a prompt to the configured LLM endpoint and return its response."""

    response = requests.post(
        endpoint,
        json={"model": model, "prompt": prompt, "stream": False},
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    output = data.get("response") or data.get("output")
    if not output:
        raise LLMInferenceError("Antwort enthält keinen Text.")
    return str(output).strip()


def infer_gender_for_listing(
    listing: Listing,
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    """Use an LLM to guess the gender when it is missing on the site."""

    prompt = _build_gender_prompt(listing)
    if not prompt:
        return None

    logger.info("Leite Geschlechtsinferenz per LLM ein für Anzeige: %s", listing.url)
    return query_llm(prompt, model=model, endpoint=endpoint, timeout=timeout)
