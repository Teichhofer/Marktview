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
import math
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit
from typing import Optional

import re

import requests

from .models import Listing

logger = logging.getLogger(__name__)
io_logger = logging.getLogger(f"{__name__}.io")
io_logger.propagate = False

# Default Ollama setup. A lightweight text generation model is used to keep
# startup fast while still supporting the /api/generate endpoint.
DEFAULT_MODEL = "gemma3:1b"
DEFAULT_ENDPOINT = "http://127.0.0.1:11434/api/generate"
DEFAULT_TIMEOUT = 30.0


def configure_llm_logging(log_dir: str | Path) -> None:
    """Configure a dedicated log file for LLM traffic."""

    log_path = Path(log_dir) / "llm.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    for handler in io_logger.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == log_path:
            return

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    io_logger.addHandler(handler)
    io_logger.setLevel(logging.INFO)


class LLMInferenceError(RuntimeError):
    """Raised when the LLM endpoint cannot return a valid answer."""


class _LocalOllamaService:  # pragma: no cover - integration-heavy logic
    """Start and manage a local Ollama server when needed."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._process: subprocess.Popen[str] | None = None
        self._started_by_app = False

    def _suggested_thread_count(self) -> int:
        cpu_count = os.cpu_count() or 1
        return max(1, math.ceil(cpu_count * 0.5))

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
                thread_count = self._suggested_thread_count()
                env = os.environ.copy()
                env["OLLAMA_NUM_THREADS"] = str(thread_count)

                logger.info(
                    "Starte lokalen Ollama-Server mit %s Threads …", thread_count
                )
                self._process = subprocess.Popen(
                    [binary, "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=env,
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
        "Antworte ausschließlich mit einer einzigen Zeile im Format "
        "'weiblich/männlich/divers/unbekannt 0-100%'. Keine spitzen Klammern oder andere Sonderzeichen, "
        "keine weiteren Wörter, keine Namen, keine Erklärungen oder Beispiele. "
        "Antworte nur mit dem wahrscheinlichste Geschlecht und der Wahrscheinlichkeit. "
        "Die Prozentzahl darf nicht 50% sein. "
        "Passagen wie 'ich bin männlich', 'ich bin m' oder ähnliche Selbstbeschreibungen "
        "sind eindeutige Hinweise auf männlich."
    )
    parts.append(question)
    return "\n\n".join(part for part in parts if part)


def _build_target_audience_prompt(listing: Listing) -> str:
    """Construct a prompt to infer the intended audience of the listing."""

    parts = ["Anzeigetext:"]
    if listing.title:
        parts.append(f"Titel: {listing.title}")
    if listing.body:
        parts.append(listing.body)
    if listing.username and listing.username != "nicht angegeben":
        parts.append(f"Nutzername: {listing.username}")

    question = (
        "Du bist ein präziser Textklassifizierer. Bestimme, an welches Geschlecht sich die Anzeige richtet "
        "(angesprochene Zielgruppe, nicht das Geschlecht der schreibenden Person). Wähle strikt eines der "
        "Wörter 'männlich', 'weiblich', 'divers' (für trans/non-binär), 'bi' (wenn explizit beide oder alle gemeint) "
        "oder 'unbekannt', falls der Text keine eindeutigen Hinweise liefert. Wenn der Text mehrere Geschlechter anspricht, "
        "nutze 'bi'. Antworte ausschließlich mit genau diesem einen Wort, ohne Begründung oder weitere Zeichen."
    )
    parts.append(question)
    return "\n\n".join(part for part in parts if part)


def _normalize_gender_output(raw_output: str) -> str:
    """Normalize LLM output to the expected 'geschlecht <zahl>%'-format."""

    cleaned = raw_output.replace("<", " ").replace(">", " ").strip()
    cleaned = " ".join(cleaned.split())

    gender_pattern = re.compile(r"\b(weiblich|männlich|divers|unbekannt)\b", re.IGNORECASE)
    gender_match = gender_pattern.search(cleaned)
    if not gender_match:
        raise LLMInferenceError("Antwort enthält kein erkennbares Geschlecht.")

    percent_match = re.search(r"(\d{1,3})\s*%?", cleaned)
    if not percent_match:
        # Einige Modelle ignorieren gelegentlich die Anweisung, eine Zahl
        # zurückzugeben. In diesem Fall wird die Antwort nicht mehr hart
        # abgelehnt, sondern mit einer konservativen Standardwahrscheinlichkeit
        # versehen, damit die Verarbeitung der Anzeige nicht fehlschlägt.
        percent = 50
    else:
        percent = min(max(int(percent_match.group(1)), 0), 100)

    gender = gender_match.group(1).lower()
    return f"{gender} {percent}%"


def _normalize_target_audience_output(raw_output: str) -> str:
    """Normalize LLM output for the target audience question."""

    cleaned = raw_output.replace("<", " ").replace(">", " ").strip()
    cleaned = " ".join(cleaned.split())

    synonyms = {
        "weiblich": {"weiblich", "frau", "frauen", "damen"},
        "männlich": {"männlich", "mann", "männer", "herren"},
        "divers": {"divers", "nonbinär", "non-binary", "trans", "trans*", "transgender"},
        "bi": {"bi", "bisexuell", "beide", "alle"},
        "unbekannt": {"unbekannt", "unklar", "k.A."},
    }

    for normalized, keywords in synonyms.items():
        pattern = re.compile(r"\b(" + "|".join(re.escape(k) for k in keywords) + r")\b", re.IGNORECASE)
        if pattern.search(cleaned):
            return normalized

    raise LLMInferenceError("Antwort enthält keine erkennbaren Zielgruppe.")


class LLMClient:  # pragma: no cover - network-heavy client logic
    """Encapsulate LLM interactions including logging and configuration."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        endpoint: str = DEFAULT_ENDPOINT,
        timeout: float = DEFAULT_TIMEOUT,
        service: _LocalOllamaService | None = None,
    ) -> None:
        self.model = model
        self.endpoint = endpoint
        self.timeout = timeout
        self._service = service or _ollama_service

    def query(
        self,
        prompt: str,
        *,
        normalizer=_normalize_gender_output,
        enforce_confidence: bool = True,
        fallback: str = "unbekannt 0%",
    ) -> str:
        """Send a prompt to the configured LLM endpoint and return its response."""

        if self.endpoint == DEFAULT_ENDPOINT:
            self._service.ensure_running(model=self.model, endpoint=self.endpoint)

        logger.debug(
            "Sende LLM-Anfrage: Modell='%s', Endpoint='%s', Timeout=%.1fs",
            self.model,
            self.endpoint,
            self.timeout,
        )
        io_logger.info(
            "→ Prompt (Modell='%s', Endpoint='%s'):\n%s",
            self.model,
            self.endpoint,
            prompt,
        )

        def _send_request() -> requests.Response:
            response = requests.post(
                self.endpoint,
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response

        max_attempts = 10
        for attempt in range(1, max_attempts + 1):
            try:
                response = _send_request()
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else ""
                body = exc.response.text if exc.response is not None else "<no response>"
                logger.error(
                    "LLM-HTTP-Fehler (Status %s) bei Endpoint '%s' mit Modell '%s': %s",
                    status,
                    self.endpoint,
                    self.model,
                    body,
                )
                if status == 404 and self.endpoint == DEFAULT_ENDPOINT:
                    logger.info(
                        "LLM-Endpunkt antwortet mit 404. Starte lokalen Ollama-Server neu und versuche es erneut …"
                    )
                    self._service.stop()
                    self._service.ensure_running(model=self.model, endpoint=self.endpoint)
                    response = _send_request()
                else:
                    if status == 404:
                        hint = (
                            "Der LLM-Endpunkt antwortet mit 404 Not Found. Läuft Ollama "
                            f"auf {self.endpoint}? Starte den Dienst mit 'ollama serve' oder passe den Endpunkt an."
                        )
                    else:
                        hint = f"LLM-Anfrage fehlgeschlagen (HTTP {status})."
                    if attempt == max_attempts:
                        raise LLMInferenceError(hint) from exc
                    logger.info(
                        "HTTP-Fehler – wiederhole Anfrage (%s/%s)", attempt + 1, max_attempts
                    )
                    continue
            except requests.exceptions.RequestException as exc:  # noqa: PERF203
                logger.exception(
                    "LLM-Endpunkt konnte nicht erreicht werden: Endpoint='%s', Modell='%s'",
                    self.endpoint,
                    self.model,
                )
                hint = "LLM-Endpunkt konnte nicht erreicht werden."
                if self.endpoint == DEFAULT_ENDPOINT:
                    hint += (
                        " Ist Ollama installiert und läuft 'ollama serve'? Falls nicht, installiere bzw. starte den Dienst "
                        "oder konfiguriere einen eigenen Endpunkt."
                    )
                if attempt == max_attempts:
                    raise LLMInferenceError(f"{hint} Details: {exc}") from exc
                logger.info(
                    "Netzwerkfehler – wiederhole Anfrage (%s/%s)", attempt + 1, max_attempts
                )
                continue

            data = response.json()
            output = data.get("response") or data.get("output")
            if not output:
                logger.error(
                    "LLM-Antwort ohne Text: Keys=%s, Endpoint='%s', Modell='%s'",
                    list(data.keys()),
                    self.endpoint,
                    self.model,
                )
                raise LLMInferenceError("Antwort enthält keinen Text.")

            cleaned_output = str(output).strip()

            try:
                normalized_output = normalizer(cleaned_output) if normalizer else cleaned_output
            except LLMInferenceError:
                if attempt < max_attempts:
                    logger.info(
                        "LLM-Antwort erfüllt Qualitätsanforderungen nicht – wiederhole Anfrage (%s/%s)",
                        attempt + 1,
                        max_attempts,
                    )
                    continue
                logger.warning(
                    "LLM-Antwort erfüllt Qualitätsanforderungen nicht – nutze Fallback '%s'",
                    fallback,
                )
                return fallback

            if enforce_confidence:
                confidence_match = re.search(r"(\d{1,3})%", normalized_output)
                confidence = int(confidence_match.group(1)) if confidence_match else 0
                if confidence < 50:
                    if attempt < max_attempts:
                        logger.info(
                            "LLM-Antwort mit geringer Wahrscheinlichkeit (%s%%) – wiederhole Anfrage (%s/%s)",
                            confidence,
                            attempt + 1,
                            max_attempts,
                        )
                        continue
                    logger.warning(
                        "LLM-Antwort mit geringer Wahrscheinlichkeit (%s%%) – verwende Ergebnis des letzten Versuchs",
                        confidence,
                    )

            io_logger.info(
                "← Antwort (Modell='%s', Endpoint='%s'): %s",
                self.model,
                self.endpoint,
                cleaned_output,
            )
            return normalized_output

    def infer_gender_for_listing(self, listing: Listing) -> Optional[str]:
        """Use an LLM to guess the gender when it is missing on the site."""

        prompt = _build_gender_prompt(listing)
        if not prompt:
            return None

        logger.info(
            "Leite Geschlechtsinferenz per LLM ein für Anzeige: %s", listing.url
        )
        logger.debug(
            "Verwende Modell '%s' am Endpoint '%s' für Anzeige %s",
            self.model,
            self.endpoint,
            listing.url,
        )
        try:
            return self.query(prompt)
        except Exception:
            logger.exception(
                "Geschlechtsinferenz fehlgeschlagen für Anzeige: %s", listing.url
            )
            raise

    def infer_target_audience_for_listing(self, listing: Listing) -> Optional[str]:
        """Use an LLM to infer the intended audience of a listing."""

        prompt = _build_target_audience_prompt(listing)
        if not prompt:
            return None

        logger.info(
            "Leite Zielgruppeninferenz per LLM ein für Anzeige: %s", listing.url
        )
        logger.debug(
            "Verwende Modell '%s' am Endpoint '%s' für Zielgruppenanalyse von Anzeige %s",
            self.model,
            self.endpoint,
            listing.url,
        )
        try:
            return self.query(
                prompt,
                normalizer=_normalize_target_audience_output,
                enforce_confidence=False,
                fallback="unbekannt",
            )
        except Exception:
            logger.exception(
                "Zielgruppeninferenz fehlgeschlagen für Anzeige: %s", listing.url
            )
            raise


_default_client = LLMClient()


def infer_gender_for_listing(
    listing: Listing,
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    client = (
        _default_client
        if (model, endpoint, timeout)
        == (DEFAULT_MODEL, DEFAULT_ENDPOINT, DEFAULT_TIMEOUT)
        else LLMClient(model=model, endpoint=endpoint, timeout=timeout)
    )
    return client.infer_gender_for_listing(listing)


def infer_target_audience_for_listing(
    listing: Listing,
    *,
    model: str = DEFAULT_MODEL,
    endpoint: str = DEFAULT_ENDPOINT,
    timeout: float = DEFAULT_TIMEOUT,
) -> Optional[str]:
    client = (
        _default_client
        if (model, endpoint, timeout)
        == (DEFAULT_MODEL, DEFAULT_ENDPOINT, DEFAULT_TIMEOUT)
        else LLMClient(model=model, endpoint=endpoint, timeout=timeout)
    )
    return client.infer_target_audience_for_listing(listing)
