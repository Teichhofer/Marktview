import asyncio
from types import SimpleNamespace

import pytest

from marktview import parsers
from marktview.models import Listing


class FakeElement:
    def __init__(self, title=None, url=None):
        self.attrs = {"title": title, "data-onclick-url": url}

    async def get_attribute(self, name):
        return self.attrs.get(name)


class FakeListingLocator:
    def __init__(self, elements):
        self._elements = elements

    async def count(self):
        return len(self._elements)

    def nth(self, index):
        return self._elements[index]


class FakeDetailLocator:
    def __init__(self, text=None, raise_error=False):
        self.text = text
        self.raise_error = raise_error

    async def inner_text(self):
        if self.raise_error:
            raise RuntimeError("locator error")
        return self.text

    async def all_inner_texts(self):
        if not self.text:
            return []
        return self.text.split("\n")


class FakePage:
    def __init__(self, mapping=None):
        self.mapping = mapping or {}
        self.visits = []

    def locator(self, selector):
        if selector == "li.clsy-c-result-list-item":
            return FakeListingLocator(self.mapping.get("listings", []))
        return self.mapping.get(selector, FakeDetailLocator())

    async def goto(self, url):
        self.visits.append(url)

    async def wait_for_load_state(self, _):
        pass

    async def wait_for_timeout(self, _):
        pass


@pytest.mark.asyncio
async def test_parse_listings_filters_and_builds_full_url():
    elements = [
        FakeElement(title=" ", url="/missing"),
        FakeElement(title="Ad", url="/listing"),
        FakeElement(title="Werbung", url="/feed.solads.media/test"),
    ]
    page = FakePage({"listings": elements})
    listings = await parsers.parse_listings(page)
    assert len(listings) == 1
    assert listings[0].url.startswith("https://erotik.markt.de")


@pytest.mark.asyncio
async def test_parse_listing_details_populates_fields():
    listing = Listing(title="Ad", url="https://erotik.markt.de/listing")
    page = FakePage(
        {
            "div.clsy-c-expose-details__location": FakeDetailLocator("PLZ 12345 Berlin"),
            "div.clsy-c-expose-details__date": FakeDetailLocator("Heute"),
            "div#clsy-c-expose-body": FakeDetailLocator("Body"),
            "div.clsy-c-userbox__profile-name": FakeDetailLocator("User"),
            "span.clsy-attribute-list__label": FakeDetailLocator(
                "Geschlecht\nInteresse an Geld\nAnzeigenkennung"
            ),
            "span.clsy-attribute-list__description": FakeDetailLocator(
                "männlich\nJa\nABC123"
            ),
        }
    )

    await parsers.parse_listing_details(page, listing)
    assert listing.postal_code == "12345"
    assert listing.created_at == "Heute"
    assert listing.body == "Body"
    assert listing.username == "User"
    assert listing.gender == "männlich"
    assert listing.financial_interest == "Ja"
    assert listing.listing_id == "ABC123"


@pytest.mark.asyncio
async def test_safe_inner_text_handles_errors():
    page = FakePage({"div.error": FakeDetailLocator(raise_error=True)})
    assert await parsers._safe_inner_text(page, "div.error") is None
