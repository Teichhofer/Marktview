"""High-level scraping orchestration."""

import asyncio
from pathlib import Path
from typing import List, Set

from playwright.async_api import BrowserContext

from .config import NETWORK_IDLE_DELAY, PAGE_READY_DELAY
from .excel_writer import write_listings_to_excel
from .models import Listing
from .page_actions import accept_cookies, confirm_age, wait_for_page_ready
from .parsers import parse_listing_details, parse_listings


async def _populate_listing(
    context: BrowserContext,
    listing: Listing,
    concurrency: asyncio.Semaphore,
    known_listing_ids: Set[str],
) -> None:
    async with concurrency:
        detail_page = await context.new_page()
        try:
            print(f"[INFO] Lade Details für: {listing.title}")
            await parse_listing_details(detail_page, listing)
            await asyncio.sleep(NETWORK_IDLE_DELAY)
            if listing.listing_id:
                known_listing_ids.add(listing.listing_id)
        except Exception as exc:  # noqa: BLE001
            print(f"[WARN] Fehler bei {listing.url}: {exc}")
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
) -> List[Listing]:
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
    current_page = 0

    while current_page < max_pages:
        print(f"[INFO] Verarbeite Seite {current_page + 1}")
        await wait_for_page_ready(page, delay=NETWORK_IDLE_DELAY)

        listings = await parse_listings(page)
        if not listings:
            dump_path = Path(f"dump_page_{current_page + 1}.html")
            dump_path.write_text(await page.content(), encoding="utf-8")
            print(f"[WARN] Keine Anzeigen gefunden – Dump gespeichert: {dump_path}")
            break

        filtered_listings: List[Listing] = []
        for listing in listings:
            if any(
                listing_id and listing_id in listing.url for listing_id in known_listing_ids
            ):
                print(
                    f"[INFO] Anzeige übersprungen (bereits vorhanden): {listing.url}"
                )
                continue
            filtered_listings.append(listing)

        if not filtered_listings:
            print("[INFO] Alle Anzeigen auf dieser Seite sind bereits vorhanden.")
        else:
            semaphore = asyncio.Semaphore(concurrency_limit)
            await asyncio.gather(
                *(
                    _populate_listing(context, listing, semaphore, known_listing_ids)
                    for listing in filtered_listings
                )
            )

            all_listings.extend(filtered_listings)

            if progress_path:
                write_listings_to_excel(filtered_listings, progress_path)

        next_button = page.locator("button.clsy-c-pagination__next")
        try:
            is_visible = await next_button.is_visible(timeout=3000)
        except Exception:  # noqa: BLE001
            is_visible = False

        if not is_visible:
            print("[INFO] Keine weitere Seite gefunden.")
            break

        await next_button.click()
        current_page += 1

    await page.close()
    return all_listings
