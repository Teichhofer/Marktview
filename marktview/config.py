"""Configuration defaults for the Markt.de scraper."""

START_URL = "https://erotik.markt.de/74670-forchtenberg/anzeigen/fetisch/?radius=100"
OUTPUT_FILE = "anzeigen.xlsx"
MAX_PAGES = 50
CONCURRENCY = 2
HEADLESS = False
NETWORK_IDLE_DELAY = 1.0
PAGE_READY_DELAY = 2.0
