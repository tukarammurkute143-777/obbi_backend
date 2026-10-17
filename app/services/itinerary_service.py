"""
Persistence for generated itineraries (`itineraries` table) and their PDFs.

Sync DB helpers are run in a thread by the async wrappers. Nothing here raises
to the caller for database trouble: lookups return None, saves return None,
and the callers decide what that means for the response.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from app.core.database import db
from app.services import itinerary_pdf_service

logger = logging.getLogger("itinerary_service")

_UUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


def is_valid_id(value: str) -> bool:
    return bool(_UUID.match(value or ""))


def _save(user_id, inputs: dict, itinerary: dict) -> dict:
    return db.table("itineraries").insert({
        "user_id": user_id,
        "from_city": inputs["from"],
        "to_city": inputs["to"],
        "days": inputs["days"],
        "people": inputs["people"],
        "budget": inputs["budget"],
        "trip_type": inputs["trip_type"],
        "itinerary_data": itinerary,
    }).execute().data[0]


async def save_itinerary(user_id: str, inputs: dict, itinerary: dict) -> Optional[str]:
    """The new itinerary id, or None if it could not be saved."""
    try:
        row = await asyncio.to_thread(_save, user_id, inputs, itinerary)
        return row["id"]
    except Exception as e:
        logger.error("Saving itinerary failed: %s", type(e).__name__)
        return None


def _get(itinerary_id: str) -> Optional[dict]:
    rows = db.table("itineraries").select("*").eq("id", itinerary_id) \
        .limit(1).execute().data
    return rows[0] if rows else None


async def get_itinerary(itinerary_id: str) -> Optional[dict]:
    try:
        return await asyncio.to_thread(_get, itinerary_id)
    except Exception as e:
        logger.error("Loading itinerary failed: %s", type(e).__name__)
        raise LookupError("database unavailable") from None


def _update(itinerary_id: str, fields: dict) -> None:
    db.table("itineraries").update(fields).eq("id", itinerary_id).execute()


async def update_itinerary(itinerary_id: str, **fields) -> None:
    """Best-effort flag/path update; a failure here must not fail the request."""
    try:
        await asyncio.to_thread(_update, itinerary_id, fields)
    except Exception as e:
        logger.error("Updating itinerary %s failed: %s", itinerary_id,
                     type(e).__name__)


def _customer_name(user_id: str) -> str:
    rows = db.table("users").select("name").eq("id", user_id).limit(1).execute().data
    return (rows[0].get("name") if rows else None) or "Traveller"


async def ensure_pdf(row: dict) -> str:
    """
    Path of a PDF for this itinerary row, re-rendering it from the stored JSON
    when the cached file is gone. Raises on render failure.
    """
    if itinerary_pdf_service.is_managed_pdf(row.get("pdf_path")):
        return row["pdf_path"]

    try:
        name = await asyncio.to_thread(_customer_name, row["user_id"])
    except Exception:
        name = "Traveller"
    path = await asyncio.to_thread(
        itinerary_pdf_service.generate_pdf,
        row["itinerary_data"] or {},
        name,
        {k: row.get(k) for k in ("from_city", "to_city", "days", "people",
                                 "budget", "trip_type")},
    )
    await update_itinerary(row["id"], pdf_path=path)
    return path


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
