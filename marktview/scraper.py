"""High-level scraping orchestration."""

import asyncio
import logging
from pathlib import Path
from typing import List, Set

from playwright.async_api import BrowserContext

from .config import NETWORK_IDLE_DELAY, PAGE_READY_DELAY
from .excel_writer import write_listings_to_excel
from .llm import infer_gender_for_listing, infer_target_audience_for_listing
from .models import Listing
from .page_actions import accept_cookies, confirm_age, wait_for_page_ready
from .parsers import parse_listing_details, parse_listings

logger = logging.getLogger(__name__)


async def _populate_listing(
    context: BrowserContext,
    listing: Listing,
    concurrency: asyncio.Semaphore,
    known_listing_ids: Set[str],
) -> None:  # pragma: no cover - requires live browser
    async with concurrency:
        detail_page = await context.new_page()
        try:
            logger.info("Lade Details für: %s", listing.title)
            await parse_listing_details(detail_page, listing)
            await asyncio.sleep(NETWORK_IDLE_DELAY)

            if listing.gender.lower() == "nicht angegeben":
                try:
                    llm_gender = await asyncio.to_thread(
                        infer_gender_for_listing,
                        listing,
                    )
                    if llm_gender:
                        listing.gender = llm_gender
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "Geschlecht konnte nicht per LLM ermittelt werden: %s", exc,
                        exc_info=True,
                    )

                if listing.gender.lower() == "nicht angegeben":
                    listing.gender = "unbekannt 0%"

            try:
                audience = await asyncio.to_thread(
                    infer_target_audience_for_listing,
                    listing,
                )
                if audience:
                    listing.target_audience = audience
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Zielgruppe konnte nicht per LLM ermittelt werden: %s", exc,
                    exc_info=True,
                )

            if listing.listing_id:
                known_listing_ids.add(listing.listing_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fehler bei %s: %s", listing.title, exc, exc_info=True)
        finally:
            await detail_page.close()


async def scrape_pages(
    context: BrowserContext,
    start_url: str,
    *,
    max_pages: int,
    concurrency_limit: int,
    known_listing_ids: Set[str] | None = None,
    progress_path: str | Path | None = None,
) -> List[Listing]:  # pragma: no cover - orchestrates browser automation
    """Scrape multiple listing pages starting from ``start_url``."""

    page = await context.new_page()

    await page.goto(start_url)
    await wait_for_page_ready(page, delay=PAGE_READY_DELAY)

    await accept_cookies(page)
    await confirm_age(page)

    await page.goto(start_url)
    await wait_for_page_ready(page, delay=PAGE_READY_DELAY)

    all_listings: List[Listing] = []
    known_listing_ids = known_listing_ids or set()
    processed_count = 0
    added_count = 0
    current_page = 0

    while current_page < max_pages:
        logger.info("Verarbeite Seite %s", current_page + 1)
        await wait_for_page_ready(page, delay=NETWORK_IDLE_DELAY)

        listings = await parse_listings(page)
        if not listings:
            dump_path = Path(f"dump_page_{current_page + 1}.html")
            dump_path.write_text(await page.content(), encoding="utf-8")
            logger.warning(
                "Keine Anzeigen gefunden – Dump gespeichert: %s", dump_path
            )
            break

        processed_count += len(listings)
        filtered_listings: List[Listing] = []
        for listing in listings:
            if any(
                listing_id and listing_id in listing.url for listing_id in known_listing_ids
            ):
                logger.info(
                    "Anzeige übersprungen (bereits vorhanden): %s", listing.title
                )
                continue
            filtered_listings.append(listing)

        if not filtered_listings:
            logger.info("Alle Anzeigen auf dieser Seite sind bereits vorhanden.")
        else:
            semaphore = asyncio.Semaphore(concurrency_limit)
            for listing in filtered_listings:
                # Stelle sicher, dass die nächste Anzeige erst verarbeitet wird,
                # wenn die optionale Geschlechtsbestimmung per LLM abgeschlossen ist.
                await _populate_listing(context, listing, semaphore, known_listing_ids)

            all_listings.extend(filtered_listings)
            added_count += len(filtered_listings)

            if progress_path:
                write_listings_to_excel(filtered_listings, progress_path)

        next_button = page.locator("button.clsy-c-pagination__next")
        try:
            is_visible = await next_button.is_visible(timeout=3000)
        except Exception:  # noqa: BLE001
            is_visible = False

        if not is_visible:
            logger.info("Keine weitere Seite gefunden.")
            break

        await next_button.click()
        current_page += 1

    logger.info(
        "Lauf abgeschlossen: %s Anzeigen verarbeitet, %s zur Liste hinzugefügt.",
        processed_count,
        added_count,
    )

    await page.close()
    return all_listings
