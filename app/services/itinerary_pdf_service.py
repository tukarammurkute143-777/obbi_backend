"""
Branded itinerary PDF (fpdf2).

PDFs are written to <tempdir>/itineraries/<uuid>.pdf. That disk is a cache, not
storage: on Railway/Render it is wiped on every deploy, so callers regenerate
from the itinerary JSON in the database whenever the file is missing.

Text is drawn with the built-in Helvetica font, which only covers Latin-1.
Anything outside it (₹, →, emoji, Devanagari) is transliterated or replaced
with '?' rather than failing the whole document.
"""

import logging
import os
import re
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from fpdf import FPDF

from app.core.config import settings

logger = logging.getLogger("itinerary_pdf")

ITINERARY_DIR = Path(tempfile.gettempdir()) / "itineraries"
MAX_AGE_SECONDS = 24 * 3600

BRAND = (230, 120, 20)      # Obii orange
INK = (35, 35, 40)
MUTED = (110, 110, 120)
SOFT = (252, 244, 235)

_REPLACEMENTS = {
    "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", "→": "->", "←": "<-", "•": "-", "₹": "Rs ", " ": " ",
}


def _t(value) -> str:
    """Latin-1-safe text, with over-long unbreakable tokens split so a long URL
    cannot overflow the line and crash fpdf2."""
    text = "" if value is None else str(value)
    for src, dst in _REPLACEMENTS.items():
        text = text.replace(src, dst)
    text = text.encode("latin-1", "replace").decode("latin-1")
    return re.sub(r"(\S{50})(?=\S)", r"\1 ", text)


class _ItineraryPDF(FPDF):
    def __init__(self, phone: str):
        super().__init__(format="A4")
        self.phone = phone
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(16, 16, 16)

    def header(self):
        self.set_fill_color(*BRAND)
        self.rect(0, 0, 210, 22, style="F")
        self.set_xy(16, 6)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 18)
        self.cell(0, 10, "Obii Cabs", new_x="LMARGIN", new_y="NEXT")
        self.set_xy(16, 14)
        self.set_font("Helvetica", "", 9)
        self.cell(0, 5, "Your trip, planned", new_x="LMARGIN", new_y="NEXT")
        self.set_y(30)

    def footer(self):
        self.set_y(-16)
        self.set_draw_color(*BRAND)
        self.line(16, self.get_y(), 194, self.get_y())
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*MUTED)
        self.cell(0, 8, _t(f"Obii Cabs  |  Book or ask us anything: {self.phone}"),
                  align="L")
        self.cell(0, 8, f"Page {self.page_no()}", align="R")


def _heading(pdf: _ItineraryPDF, text: str, size: int = 13):
    pdf.set_font("Helvetica", "B", size)
    pdf.set_text_color(*BRAND)
    pdf.multi_cell(0, 7, _t(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*INK)


def _para(pdf: _ItineraryPDF, text: str, style: str = "", size: int = 10,
          color=INK, indent: float = 0):
    pdf.set_font("Helvetica", style, size)
    pdf.set_text_color(*color)
    pdf.set_x(pdf.l_margin + indent)
    pdf.multi_cell(0, 5.5, _t(text), new_x="LMARGIN", new_y="NEXT")


def _build(itinerary: dict, customer_name: str, trip: dict) -> _ItineraryPDF:
    pdf = _ItineraryPDF(settings.OWNER_PHONE or "")
    pdf.add_page()

    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 20)
    pdf.multi_cell(
        0, 10, _t(f"{trip.get('from_city', '')} to {trip.get('to_city', '')}"),
        new_x="LMARGIN", new_y="NEXT")
    _para(pdf, f"Prepared for {customer_name or 'Traveller'}  -  "
               f"{datetime.now().strftime('%d %b %Y')}", color=MUTED)
    pdf.ln(2)

    # Trip details band
    details = [
        ("Days", trip.get("days")),
        ("Travellers", trip.get("people")),
        ("Budget", str(trip.get("budget") or "").title()),
        ("Trip type", str(trip.get("trip_type") or "").title()),
    ]
    pdf.set_fill_color(*SOFT)
    width = pdf.epw / len(details)
    y = pdf.get_y()
    for i, (label, value) in enumerate(details):
        pdf.set_xy(pdf.l_margin + i * width, y)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.cell(width, 6, _t(label.upper()), fill=True, new_x="LEFT", new_y="NEXT")
        pdf.set_x(pdf.l_margin + i * width)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(*INK)
        pdf.cell(width, 8, _t(value), fill=True)
    pdf.set_y(y + 18)

    if itinerary.get("summary"):
        _para(pdf, itinerary["summary"], style="I", size=10.5)
        pdf.ln(2)

    for day in itinerary.get("days") or []:
        if pdf.get_y() > 245:
            pdf.add_page()
        pdf.ln(2)
        _heading(pdf, f"Day {day.get('day', '')}: {day.get('title', '')}", 13)

        for slot in day.get("slots") or []:
            when = str(slot.get("time") or "").title()
            hours = slot.get("duration_hours")
            tag = f"{when}" + (f"  ({hours} hrs)" if hours else "")
            _para(pdf, tag, style="B", size=9, color=MUTED, indent=2)
            _para(pdf, f"{slot.get('place', '')} - {slot.get('activity', '')}",
                  indent=2)
            if slot.get("tips"):
                _para(pdf, f"Tip: {slot['tips']}", style="I", size=9,
                      color=MUTED, indent=6)
            pdf.ln(1)

        meals = day.get("meals") or {}
        meal_line = "   ".join(
            f"{k.title()}: {v}" for k, v in meals.items() if v)
        if meal_line:
            _para(pdf, meal_line, size=9.5, indent=2)
        if day.get("hotel"):
            _para(pdf, f"Stay: {day['hotel']}", style="B", size=10, indent=2)

    pdf.ln(3)
    if itinerary.get("cab_suggestion"):
        _heading(pdf, "Recommended Obii Cabs vehicle", 12)
        _para(pdf, itinerary["cab_suggestion"])
        _para(pdf, "For rates, please contact Obii Cabs.", style="I", size=9,
              color=MUTED)
        pdf.ln(2)

    tips = itinerary.get("important_tips") or []
    if tips:
        _heading(pdf, "Travel tips", 12)
        for tip in tips:
            _para(pdf, f"-  {tip}", indent=2)
    return pdf


def _cleanup_old_files() -> None:
    cutoff = time.time() - MAX_AGE_SECONDS
    try:
        for f in ITINERARY_DIR.glob("*.pdf"):
            if f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("Itinerary PDF cleanup failed: %s", type(e).__name__)


def generate_pdf(itinerary_data: dict, customer_name: str,
                 trip_details: dict) -> str:
    """
    Render the itinerary and return the file path. Blocking (CPU + disk): call
    it with asyncio.to_thread from async code. Raises on failure.
    """
    ITINERARY_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_old_files()
    path = ITINERARY_DIR / f"{uuid.uuid4()}.pdf"
    _build(itinerary_data, customer_name, trip_details).output(str(path))
    return str(path)


def is_managed_pdf(path: Optional[str]) -> bool:
    """True for an existing file inside ITINERARY_DIR. Anything else (a path
    that came from a request or the database) must never be read or emailed."""
    if not path:
        return False
    try:
        resolved = Path(path).resolve()
        return (resolved.parent == ITINERARY_DIR.resolve()
                and resolved.suffix == ".pdf" and resolved.is_file())
    except (OSError, ValueError):
        return False
