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
  --headless  # oder --no-headless für sichtbaren Browser
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

Parameter sind optional; ohne Flags werden Standardwerte aus `marktview/config.py` verwendet.

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
