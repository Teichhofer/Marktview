from marktview.models import Listing


def test_listing_strips_fields():
    listing = Listing(
        title="  Title  ",
        url="  https://example.com  ",
        postal_code=" 12345 ",
        created_at=" 2024-01-01 ",
        body="  Body text \n  ",
        gender="  weiblich  ",
        target_audience="  männlich  ",
        financial_interest="  nein  ",
        listing_id="  ID-1  ",
        username="  user  ",
    )

    assert listing.title == "Title"
    assert listing.url == "https://example.com"
    assert listing.postal_code == "12345"
    assert listing.created_at == "2024-01-01"
    assert listing.body == "Body text"
    assert listing.gender == "weiblich"
    assert listing.target_audience == "männlich"
    assert listing.financial_interest == "nein"
    assert listing.listing_id == "ID-1"
    assert listing.username == "user"
