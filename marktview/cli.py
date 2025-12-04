"""Command-line entry point for scraping Markt.de listings."""

import argparse
import asyncio
import inspect
import logging
import sys
from pathlib import Path

from playwright.async_api import async_playwright

from . import config
from .excel_writer import load_existing_listing_ids, write_listings_to_excel
from .llm import configure_llm_logging
from .scraper import scrape_pages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Markt.de Listings Scraper")
    parser.add_argument(
        "--start-url",
        default=config.START_URL,
        help="Start URL für die Suche",
    )
    parser.add_argument(
        "--output",
        default=config.OUTPUT_FILE,
        help="Ausgabedatei für Excel (xlsx)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=config.MAX_PAGES,
        help="Maximale Anzahl an Ergebnisseiten",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=config.CONCURRENCY,
        help="Anzahl gleichzeitiger Detailabrufe",
    )
    parser.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=config.HEADLESS,
        help="Browser im Headless-Modus starten",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Alle 5 Minuten erneut ausführen, bis Strg+C gedrückt wird",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Logs und aktuelle Ausgabedatei löschen, ohne zu scrapen",
    )
    return parser


def parse_args() -> argparse.Namespace:
    return build_parser().parse_args()


def configure_utf8_output() -> None:
    """Ensure stdout/stderr use UTF-8 encoding.

    This prevents ``UnicodeEncodeError`` when console code pages do not
    support characters used in listing titles (e.g., emojis on Windows).
    """

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except AttributeError:
            # ``reconfigure`` not available (e.g., when stream is replaced).
            pass


async def scrape_cycle_with_context(
    context, args: argparse.Namespace, output_path: Path
) -> Path:
    existing_listing_ids = load_existing_listing_ids(output_path)

    listings = await scrape_pages(
        context,
        args.start_url,
        max_pages=args.max_pages,
        concurrency_limit=args.concurrency,
        known_listing_ids=existing_listing_ids,
        progress_path=output_path,
    )

    return write_listings_to_excel(listings, output_path)


async def run_once(args: argparse.Namespace) -> Path:
    output_path = Path(args.output)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=args.headless)

        try:
            context = await browser.new_context()
            try:
                return await scrape_cycle_with_context(context, args, output_path)
            finally:
                close_context = getattr(context, "close", None)
                if close_context:
                    maybe_coro = close_context()
                    if inspect.isawaitable(maybe_coro):
                        await maybe_coro
        finally:
            await browser.close()


async def run_loop(args: argparse.Namespace) -> None:
    output_path = Path(args.output)

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=args.headless)

        context = await browser.new_context()

        try:
            while True:
                await scrape_cycle_with_context(context, args, output_path)
                print("Erneuter Durchlauf in 5 Minuten. Abbruch mit Strg+C.")
                await asyncio.sleep(300)
        finally:
            close_context = getattr(context, "close", None)
            if close_context:
                maybe_coro = close_context()
                if inspect.isawaitable(maybe_coro):
                    await maybe_coro
            await browser.close()


def clear_artifacts(output_path: Path, log_dir: Path) -> None:
    if output_path.exists():
        output_path.unlink()

    if log_dir.exists():
        for log_file in log_dir.iterdir():
            if log_file.is_file():
                log_file.unlink()
        # Entferne leeres Verzeichnis, falls möglich
        try:
            log_dir.rmdir()
        except OSError:  # pragma: no cover - non-empty directory
            # Verzeichnis ist nicht leer oder konnte nicht entfernt werden
            pass


def main() -> None:
    args = parse_args()

    log_dir = Path("log")

    configure_utf8_output()

    if args.clear:
        clear_artifacts(Path(args.output), log_dir)
        print("Logs und Ausgabedatei wurden gelöscht.")
        return

    log_dir.mkdir(parents=True, exist_ok=True)
    configure_llm_logging(log_dir)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "marktview.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
        force=True,
    )

    try:
        if args.loop:  # pragma: no cover - manual loop mode
            asyncio.run(run_loop(args))
        else:
            asyncio.run(run_once(args))
    except KeyboardInterrupt:  # pragma: no cover - user interruption path
        print("Loop beendet.")


if __name__ == "__main__":  # pragma: no cover - entrypoint
    main()
