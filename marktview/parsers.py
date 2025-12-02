"""Parsing helpers for Markt.de listings."""

import re
from typing import List, Optional

from playwright.async_api import Page

from .models import Listing


async def parse_listings(page: Page) -> List[Listing]:
    """Parse all listing tiles on the current result page."""

    listings: List[Listing] = []
    elements = page.locator("li.clsy-c-result-list-item")

    count = await elements.count()
    for index in range(count):
        element = elements.nth(index)
        title = await element.get_attribute("title") or ""
        onclick = await element.get_attribute("data-onclick-url") or ""

        if not title.strip() or not onclick.strip():
            continue

        full_url = f"https://erotik.markt.de{onclick}"
        if "feed.solads.media" in full_url.lower():
            print(f"[INFO] Anzeige übersprungen (Werbung): {full_url}")
            continue

        listings.append(Listing(title=title, url=full_url))

    return listings


async def parse_listing_details(page: Page, listing: Listing) -> None:
    """Populate detail data for a given listing using its detail page."""

    await page.goto(listing.url)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(1000)

    location_text = await _safe_inner_text(page, "div.clsy-c-expose-details__location")
    if location_text:
        match = re.search(r"\b\d{5}\b", location_text)
        listing.postal_code = match.group(0) if match else ""

    created_at_text = await _safe_inner_text(page, "div.clsy-c-expose-details__date")
    listing.created_at = created_at_text.strip() if created_at_text else None

    body_text = await _safe_inner_text(page, "div#clsy-c-expose-body")
    listing.body = body_text.strip() if body_text else None

    username = await _safe_inner_text(page, "div.clsy-c-userbox__profile-name")
    if username:
        listing.username = username.strip()

    labels = await page.locator("span.clsy-attribute-list__label").all_inner_texts()
    descriptions = await page.locator("span.clsy-attribute-list__description").all_inner_texts()

    for label, value in zip(labels, descriptions):
        normalized_label = label.replace("\u00AD", "").strip().lower()
        cleaned_value = value.strip()

        if "geschlecht" in normalized_label:
            listing.gender = cleaned_value
        elif "interesse an geld" in normalized_label:
            listing.financial_interest = cleaned_value
        elif "anzeigenkennung" in normalized_label:
            listing.listing_id = cleaned_value


async def _safe_inner_text(page: Page, selector: str) -> Optional[str]:
    """Return inner text for ``selector``; suppresses locator errors."""

    try:
        return await page.locator(selector).inner_text()
    except Exception:  # noqa: BLE001
        return None
