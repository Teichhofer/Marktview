"""Data models used by the scraper."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class Listing:
    """Represents a Markt.de listing."""

    title: str
    url: str
    postal_code: str = ""
    created_at: Optional[str] = None
    body: Optional[str] = None
    gender: str = "nicht angegeben"
    target_audience: str = "unbekannt"
    financial_interest: str = "nicht angegeben"
    listing_id: str = "nicht angegeben"
    username: str = "nicht angegeben"

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        self.url = self.url.strip()
        self.postal_code = self.postal_code.strip()
        if self.created_at:
            self.created_at = self.created_at.strip()
        if self.body:
            self.body = self.body.strip()
        self.gender = self.gender.strip()
        self.target_audience = self.target_audience.strip()
        self.financial_interest = self.financial_interest.strip()
        self.listing_id = self.listing_id.strip()
        self.username = self.username.strip()
