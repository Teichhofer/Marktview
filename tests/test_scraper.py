import asyncio
from pathlib import Path

import pytest

from marktview import scraper
from marktview.models import Listing


class DummyPage:
    def __init__(self, listings, next_visible=True):
        self.listings = listings
        self.visited = []
        self.closed = False
        self.content_html = "<html></html>"
        self.next_visible = next_visible
        self.clicks = 0

    async def goto(self, url):
        self.visited.append(url)

    async def wait_for_load_state(self, state):  # noqa: ARG002
        return None

    async def wait_for_timeout(self, timeout):  # noqa: ARG002
        return None

    def locator(self, selector):
        if selector == "button.clsy-c-pagination__next":
            return self
        return None

    async def is_visible(self, timeout=None):  # noqa: ARG002
        self.clicks += 0
        return self.next_visible

    async def click(self):
        self.clicks += 1

    async def content(self):
        return self.content_html

    async def close(self):
        self.closed = True


class DummyContext:
    def __init__(self, pages):
        self.pages = pages
        self.created = []

    async def new_page(self):
        if not self.pages:
            page = DummyPage([], next_visible=False)
        else:
            page = self.pages.pop(0)
        self.created.append(page)
        return page


@pytest.mark.asyncio
async def test_populate_listing_infers_fields(monkeypatch):
    listing = Listing(title="Ad", url="https://example.com")
    detail_page = DummyPage([], next_visible=False)
    context = DummyContext([detail_page])

    async def fake_parse_detail(page, listing_obj):
        listing_obj.gender = "nicht angegeben"
        listing_obj.listing_id = "abc"
        listing_obj.username = "user"

    monkeypatch.setattr(scraper, "parse_listing_details", fake_parse_detail)
    monkeypatch.setattr(scraper, "infer_gender_for_listing", lambda l: "weiblich 90%")
    monkeypatch.setattr(scraper, "infer_target_audience_for_listing", lambda l: "männlich")

    await scraper._populate_listing(context, listing, asyncio.Semaphore(1), set())
    assert listing.gender.startswith("weiblich")
    assert listing.target_audience == "männlich"
    assert listing.listing_id == "abc"
    assert detail_page.closed is True


@pytest.mark.asyncio
async def test_scrape_pages_handles_duplicates_and_progress(monkeypatch, tmp_path):
    listings_page = [Listing(title="Ad1", url="https://example.com/1", listing_id="1")]
    main_page = DummyPage(listings_page, next_visible=False)
    context = DummyContext([main_page])

    monkeypatch.setattr(scraper, "wait_for_page_ready", lambda page, delay=0: asyncio.sleep(0))
    monkeypatch.setattr(scraper, "accept_cookies", lambda page: asyncio.sleep(0))
    monkeypatch.setattr(scraper, "confirm_age", lambda page: asyncio.sleep(0))

    async def fake_parse_listings(page):
        return listings_page

    async def fake_parse_details(page, listing):  # noqa: ARG001
        return None

    monkeypatch.setattr(scraper, "parse_listings", fake_parse_listings)
    monkeypatch.setattr(scraper, "parse_listing_details", fake_parse_details)
    monkeypatch.setattr(scraper, "infer_gender_for_listing", lambda listing: "weiblich 90%")
    monkeypatch.setattr(scraper, "infer_target_audience_for_listing", lambda listing: "weiblich")

    progress_path = tmp_path / "progress.xlsx"
    results = await scraper.scrape_pages(
        context,
        "https://start",
        max_pages=1,
        concurrency_limit=1,
        known_listing_ids=set(),
        progress_path=progress_path,
    )

    assert len(results) == 1
    assert progress_path.exists()
    assert main_page.closed is True


@pytest.mark.asyncio
async def test_scrape_pages_stops_without_results(monkeypatch, tmp_path):
    main_page = DummyPage([], next_visible=False)
    context = DummyContext([main_page])

    monkeypatch.setattr(scraper, "wait_for_page_ready", lambda page, delay=0: asyncio.sleep(0))
    monkeypatch.setattr(scraper, "accept_cookies", lambda page: asyncio.sleep(0))
    monkeypatch.setattr(scraper, "confirm_age", lambda page: asyncio.sleep(0))

    async def fake_parse_listings(page):
        return []

    monkeypatch.setattr(scraper, "parse_listings", fake_parse_listings)

    results = await scraper.scrape_pages(
        context,
        "https://start",
        max_pages=1,
        concurrency_limit=1,
        known_listing_ids=set(),
        progress_path=None,
    )

    assert results == []
    dump_path = Path("dump_page_1.html")
    assert dump_path.exists()
    dump_path.unlink()
