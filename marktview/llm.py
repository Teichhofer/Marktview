"""LLM helpers for gender inference when listings omit that metadata.

To avoid any manual setup, this module can bootstrap a local Ollama-Server
(``ollama serve``) on demand. When the default endpoint is used, the service is
started automatically, a small model is pulled if necessary, and the request is
sent to the freshly started instance. Custom endpoints remain supported and
are used as-is without starting a local server.
"""

from __future__ import annotations

import atexit
import logging
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit
from typing import Optional

import requests

from .models import Listing

logger = logging.getLogger(__name__)

# Default Ollama setup. A lightweight model is used to keep startup fast.
DEFAULT_MODEL = "llama3.2:1b"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_TIMEOUT = 30.0


class LLMInferenceError(RuntimeError):
    """Raised when the LLM endpoint cannot return a valid answer."""


class _LocalOllamaService:
    """Start and manage a local Ollama server when needed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._started_by_app = False

    def _base_url(self, endpoint: str) -> str:
        parsed = urlsplit(endpoint)
        return f"{parsed.scheme}://{parsed.netloc}"

    def _is_reachable(self, base_url: str) -> bool:
        try:
            response = requests.get(f"{base_url}/api/tags", timeout=3)
            return response.ok
        except Exception:  # noqa: BLE001
            return False

    def _model_exists(self, base_url: str, model: str) -> bool:
        """Check whether the requested model is already available on the server."""

        try:
            response = requests.get(f"{base_url}/api/tags", timeout=3)
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            return any(item.get("name") == model for item in models)
        except Exception:  # noqa: BLE001
            return False

    def _wait_until_ready(self, base_url: str, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._is_reachable(base_url):
                return
            time.sleep(0.5)
        raise LLMInferenceError(
            "Lokaler Ollama-Server konnte nicht gestartet werden (keine Antwort)."
        )

    def _pull_model(self, binary: str, model: str) -> None:
        result = subprocess.run(
            [binary, "pull", model],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            raise LLMInferenceError(
                f"Ollama-Modell '{model}' konnte nicht gezogen werden."
            )

    def ensure_running(self, *, model: str, endpoint: str) -> None:
        """Ensure Ollama is running and the model is available."""

        base_url = self._base_url(endpoint)

        with self._lock:
            reachable = self._is_reachable(base_url)

            binary = shutil.which("ollama")
            if not binary:
                raise LLMInferenceError(
                    "Das Programm konnte 'ollama' nicht finden. Bitte installiere "
                    "Ollama gemäß https://ollama.com/download."
                )

            if not reachable:
                logger.info("Starte lokalen Ollama-Server …")
                self._process = subprocess.Popen(
                    [binary, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self._started_by_app = True
            elif self._model_exists(base_url, model):
                return

        self._wait_until_ready(base_url)
        self._pull_model(binary, model)

    def stop(self) -> None:
        with self._lock:
            if self._process and self._started_by_app:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            self._process = None
            self._started_by_app = False


_ollama_service = _LocalOllamaService()
atexit.register(_ollama_service.stop)


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

    if endpoint == DEFAULT_ENDPOINT:
        _ollama_service.ensure_running(model=model, endpoint=endpoint)

    logger.debug(
        "Sende LLM-Anfrage: Modell='%s', Endpoint='%s', Timeout=%.1fs",
        model,
        endpoint,
        timeout,
    )

    def _send_request() -> requests.Response:
        response = requests.post(
            endpoint,
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=timeout,
        )
        response.raise_for_status()
        return response

    try:
        response = _send_request()
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else ""
        body = exc.response.text if exc.response is not None else "<no response>"
        logger.error(
            "LLM-HTTP-Fehler (Status %s) bei Endpoint '%s' mit Modell '%s': %s",
            status,
            endpoint,
            model,
            body,
        )
        if status == 404 and endpoint == DEFAULT_ENDPOINT:
            # If we get a 404 from the default endpoint, the local server might not
            # have been ready yet. Restart it once and retry the request so the
            # user does not need to manually intervene.
            logger.info(
                "LLM-Endpunkt antwortet mit 404. Starte lokalen Ollama-Server neu "
                "und versuche es erneut …"
            )
            _ollama_service.stop()
            _ollama_service.ensure_running(model=model, endpoint=endpoint)
            response = _send_request()
        else:
            if status == 404:
                hint = (
                    "Der LLM-Endpunkt antwortet mit 404 Not Found. Läuft Ollama "
                    f"auf {endpoint}? Starte den Dienst mit 'ollama serve' oder "
                    "passe den Endpunkt an."
                )
            else:
                hint = f"LLM-Anfrage fehlgeschlagen (HTTP {status})."
            raise LLMInferenceError(hint) from exc
    except requests.exceptions.RequestException as exc:  # noqa: PERF203
        logger.exception(
            "LLM-Endpunkt konnte nicht erreicht werden: Endpoint='%s', Modell='%s'",
            endpoint,
            model,
        )
        hint = "LLM-Endpunkt konnte nicht erreicht werden."
        if endpoint == DEFAULT_ENDPOINT:
            hint += (
                " Ist Ollama installiert und läuft 'ollama serve'? Falls nicht, "
                "installiere bzw. starte den Dienst oder konfiguriere einen eigenen "
                "Endpunkt."
            )
        raise LLMInferenceError(f"{hint} Details: {exc}") from exc
    data = response.json()
    output = data.get("response") or data.get("output")
    if not output:
        logger.error(
            "LLM-Antwort ohne Text: Keys=%s, Endpoint='%s', Modell='%s'",
            list(data.keys()),
            endpoint,
            model,
        )
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
    logger.debug(
        "Verwende Modell '%s' am Endpoint '%s' für Anzeige %s",
        model,
        endpoint,
        listing.url,
    )
    try:
        return query_llm(prompt, model=model, endpoint=endpoint, timeout=timeout)
    except Exception:
        logger.exception(
            "Geschlechtsinferenz fehlgeschlagen für Anzeige: %s", listing.url
        )
        raise
