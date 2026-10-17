"""
Safar's long-term memory of a customer (`user_memory`, one row per user).

Holds the last route and vehicle they asked about, how many conversations they
have had, whether they have ever had a booking (which keeps itinerary and hotel
help unlocked in every future session), and a short summary of the last
inquiry. The live conversation is in chat_session_service; this is what
survives between conversations.

Every function is fail-open: if Supabase is unreachable Safar simply behaves
like it is meeting the customer for the first time.
"""

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from app.core.database import db

logger = logging.getLogger("user_memory")

MAX_PAST_TRIPS = 10
# Statuses of a real booking in the `bookings` table that count as "has booked".
BOOKED_STATUSES = ["confirmed", "ongoing", "completed"]

_tasks: set = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mobile10(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[-10:] if len(digits) >= 10 else ""


# ------------------------------------------------------------------- reading


def _get(user_id: str) -> Optional[dict]:
    rows = db.table("user_memory").select("*").eq("user_id", user_id) \
        .limit(1).execute().data
    return rows[0] if rows else None


async def get(user_id: str) -> Optional[dict]:
    try:
        return await asyncio.to_thread(_get, str(user_id))
    except Exception as e:
        logger.warning("Reading user_memory failed: %s", type(e).__name__)
        return None


def _has_booking(mobile: str) -> bool:
    rows = (db.table("bookings").select("id").eq("customer_mobile", mobile)
            .in_("status", BOOKED_STATUSES).limit(1).execute().data)
    return bool(rows)


async def has_confirmed_booking(user: dict) -> bool:
    """True if this customer's mobile number has a real booking on record, so
    Safar does not have to take their word for it."""
    mobile = _mobile10(user.get("mobile"))
    if not mobile:
        return False
    try:
        return await asyncio.to_thread(_has_booking, mobile)
    except Exception as e:
        logger.warning("Checking bookings failed: %s", type(e).__name__)
        return False


# ------------------------------------------------------------------- writing


def _upsert(user_id: str, fields: dict) -> None:
    db.table("user_memory").upsert(
        {"user_id": user_id, **fields, "updated_at": _now()}, on_conflict="user_id"
    ).execute()


async def upsert(user_id: str, fields: dict) -> bool:
    """Merge `fields` into the user's row (creating it). Never raises."""
    if not fields:
        return True
    try:
        await asyncio.to_thread(_upsert, str(user_id), fields)
        return True
    except Exception as e:
        logger.warning("Writing user_memory failed: %s", type(e).__name__)
        return False


def upsert_in_background(user_id: str, fields: dict) -> None:
    """Same, without making the customer wait for the database."""
    if not fields:
        return
    try:
        task = asyncio.get_running_loop().create_task(upsert(user_id, fields))
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _bump(user_id: str, fields: dict) -> None:
    row = _get(user_id)
    count = ((row or {}).get("total_inquiries") or 0) + 1
    _upsert(user_id, {**fields, "total_inquiries": count})


def bump_inquiries_in_background(user_id: str, fields: Optional[dict] = None) -> None:
    """One more conversation started. Counted at the start because a
    conversation has no dependable end event; it is not atomic, so two
    conversations opening at the same instant can count as one."""
    async def run():
        try:
            await asyncio.to_thread(_bump, str(user_id), fields or {})
        except Exception as e:
            logger.warning("Counting inquiry failed: %s", type(e).__name__)

    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _forget(user_id: str) -> None:
    db.table("user_memory").delete().eq("user_id", user_id).execute()
    db.table("chat_sessions").delete().eq("user_id", user_id).execute()


async def forget(user_id: str) -> bool:
    """Erase everything Safar remembers about this user: memory and saved chats."""
    try:
        await asyncio.to_thread(_forget, str(user_id))
        return True
    except Exception as e:
        logger.error("Forgetting user failed: %s", type(e).__name__)
        return False


# --------------------------------------------------------------- snapshotting


def snapshot(row: Optional[dict]) -> dict:
    """What a new conversation needs to know, kept in the session so the
    greeting stays consistent for the whole conversation."""
    row = row or {}
    trips = row.get("past_trips") if isinstance(row.get("past_trips"), list) else []
    return {
        "returning": bool(row.get("last_inquiry_at") or row.get("last_inquiry_summary")
                          or row.get("preferred_route_to") or trips),
        "booking_ever": bool(row.get("booking_confirmed_ever")),
        "last_summary": row.get("last_inquiry_summary"),
        "last_from": row.get("preferred_route_from"),
        "last_to": row.get("preferred_route_to"),
        "preferred_vehicle": row.get("preferred_vehicle"),
        "total_inquiries": row.get("total_inquiries") or 0,
        "past_trips": trips[-MAX_PAST_TRIPS:],
        "written": {},       # what this conversation has already saved
        "written_at": 0.0,
    }
