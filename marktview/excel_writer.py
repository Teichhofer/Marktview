"""Excel export helpers for Markt.de listings."""

from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from openpyxl.styles import Alignment

from .models import Listing


HEADERS = [
    "Titel",
    "Url",
    "PLZ",
    "Erstellungsdatum",
    "Text",
    "Geschlecht",
    "Geldinteresse",
    "Anzeigenkennung",
    "Benutzername",
]


def write_listings_to_excel(listings: Iterable[Listing], path: str | Path) -> Path:
    """Write the provided listings to an Excel file."""

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Anzeigen"

    worksheet.append(HEADERS)

    for listing in listings:
        worksheet.append(
            [
                listing.title,
                listing.url,
                listing.postal_code,
                listing.created_at,
                listing.body,
                listing.gender,
                listing.financial_interest,
                listing.listing_id,
                listing.username,
            ]
        )

    wrap_alignment = Alignment(wrap_text=True)
    for cell in worksheet["E:E"]:
        cell.alignment = wrap_alignment

    worksheet.column_dimensions["A"].width = 40
    worksheet.column_dimensions["B"].width = 80
    worksheet.column_dimensions["C"].width = 10
    worksheet.column_dimensions["D"].width = 20
    worksheet.column_dimensions["E"].width = 100
    worksheet.column_dimensions["F"].width = 20
    worksheet.column_dimensions["G"].width = 20
    worksheet.column_dimensions["H"].width = 20
    worksheet.column_dimensions["I"].width = 30

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)
    print(f"[SUCCESS] Excel-Datei gespeichert unter: {output_path}")
    return output_path
