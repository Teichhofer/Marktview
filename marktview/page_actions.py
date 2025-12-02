"""Reusable page actions for handling cookie and age dialogs."""

import asyncio
from playwright.async_api import Page


async def accept_cookies(page: Page) -> None:
    """Accept the cookie banner if it is visible."""

    try:
        cookie_button = page.get_by_role("button", name="AKZEPTIEREN UND WEITER").first
        if await cookie_button.is_visible(timeout=5000):
            await cookie_button.click()
            print("[INFO] Cookie-Banner akzeptiert.")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Cookie-Banner Fehler: {exc}")


async def confirm_age(page: Page) -> None:
    """Confirm the age gate if it is shown."""

    try:
        age_button = page.locator("#btn-over-eighteen")
        if await age_button.is_visible(timeout=5000):
            await age_button.click()
            print("[INFO] Altersverifikation durchgeführt.")
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] Altersverifikation Fehler: {exc}")


async def wait_for_page_ready(page: Page, *, delay: float = 1.0) -> None:
    """Wait until the page reports network idle and give it a little extra time."""

    await page.wait_for_load_state("networkidle")
    if delay > 0:
        await asyncio.sleep(delay)
