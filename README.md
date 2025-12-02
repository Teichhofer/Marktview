# Marktview

Python-Konsolenanwendung zum Scrapen und Exportieren von Erotik-Anzeigen auf Markt.de. Die Anwendung verwendet Playwright für die Browser-Automatisierung und exportiert die Ergebnisse als Excel-Datei.

## Voraussetzungen

- Python 3.11+
- Abhängigkeiten installieren:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## Nutzung

```bash
python -m marktview \
  --start-url "https://erotik.markt.de/74670-forchtenberg/anzeigen/fetisch/?radius=100" \
  --output anzeigen.xlsx \
  --max-pages 50 \
  --concurrency 2 \
  --headless  # oder --no-headless für sichtbaren Browser \
  --clear  # löscht Logs und aktuelle Excel-Ausgabedatei
  --loop  # wiederholt den Durchlauf alle 5 Minuten bis Strg+C
```

Unter PowerShell bitte den Zeilenumbruch-Operator `` ` `` verwenden (Backslash verursacht dort den gezeigten Fehler):

```powershell
python -m marktview `
  --start-url "https://erotik.markt.de/74670-forchtenberg/anzeigen/fetisch/?radius=100" `
  --output anzeigen.xlsx `
  --max-pages 50 `
  --concurrency 2 `
  --headless  # oder --no-headless für sichtbaren Browser
```

Hinweis: Die Zeile ```powershell` dient nur als Markierung im Markdown-Beispiel und darf nicht mitkopiert werden. Der eigentliche
Aufruf beginnt mit `python -m marktview`.

Parameter sind optional; ohne Flags werden Standardwerte aus `marktview/config.py` verwendet.

### Geschlechtsinferenz ohne manuelles LLM-Setup

Bei fehlender Geschlechtsangabe startet die Anwendung automatisch eine lokale
Ollama-Instanz (`ollama serve`), zieht bei Bedarf das Modell `llama3.2:1b` und
nutzt diese für die Anfrage. Du musst den Dienst nicht separat starten; falls
du lieber einen anderen Endpoint oder ein anderes Modell verwenden möchtest,
kannst du das über die Parameter `endpoint`/`model` in
`marktview.llm.infer_gender_for_listing` tun.

## Struktur

- `marktview/models.py` – Dataklasse für Anzeigen
- `marktview/parsers.py` – Parsing-Logik für Ergebnis- und Detailseiten
- `marktview/page_actions.py` – Gemeinsame Browseraktionen (Cookies, Alterscheck)
- `marktview/scraper.py` – Steuerung des Crawlings und Parallelisierung
- `marktview/excel_writer.py` – Export der Ergebnisse nach Excel
- `marktview/cli.py` – Kommandozeilen-Einstiegspunkt

## Hinweise

- Die Anwendung startet standardmäßig mit sichtbarem Browser; mit `--headless` lässt sich der Headless-Modus aktivieren.
- Fehlerhafte Seiten werden protokolliert; wenn keine Anzeigen gefunden werden, wird ein HTML-Dump der Seite (`dump_page_<nr>.html`) abgelegt.

## Optionale Embeddings mit Ollama

Wenn du die Texte der Anzeigen lokal vektorisieren möchtest, kannst du ein Ollama-Backend mit dem Modell `qwen3-embedding:0.6b` verwenden.

1. Ollama installieren und den Embedding-Server starten:

   ```bash
   # Installation abhängig von Betriebssystem, siehe https://ollama.com/download
   ollama serve

   # Einmalig das Modell herunterladen
   ollama pull qwen3-embedding:0.6b
   ```

2. In Python die Helfer aus `marktview.ollama_embeddings` nutzen (Default-Endpunkt: `http://localhost:11434/api/embeddings`):

   ```python
   from marktview.models import Listing
   from marktview.ollama_embeddings import embed_listing, embed_listings

   listing = Listing(
       title="Beispielanzeige",
       url="https://example.com/anzeige",
       body="Kurzbeschreibung der Anzeige",
       postal_code="10115",
   )

   # Einzelnes Embedding erzeugen
   vector = embed_listing(listing)

   # Mehrere Anzeigen sequentiell vektorisieren
   vectors = embed_listings([listing], model="qwen3-embedding:0.6b")
   ```

`embed_listing` und `embed_listings` kürzen den Prompt auf 1500 Zeichen, um das Payload kompakt zu halten. Für andere Host-/Port-Kombinationen kannst du den Parameter `endpoint` überschreiben.
