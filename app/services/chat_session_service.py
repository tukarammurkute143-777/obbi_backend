"""
Safar chat sessions: Redis for speed, Supabase for keeps.

The live session lives in the cache (30 minutes since the last message). Every
turn it is also upserted to `chat_sessions` in the background, so it survives
expiry, a Redis restart or a deploy, and GET /session can still find it later.
(The spec says "persist on session end"; a session has no reliable end event -
the cache just expires - so it is written through instead of at the end.)

A session belongs to the user who created it. load() hands back whatever is
stored; callers must compare `user_id` before using it. clear() (DELETE) removes
both copies.
"""

import asyncio
import logging
import re
import weakref
from datetime import datetime, timezone
from typing import Optional

from app.core.cache import cache_delete, cache_get, cache_set
from app.core.database import db

logger = logging.getLogger("chat_session")

SESSION_TTL = 30 * 60
MAX_MESSAGES = 10

_UUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
_locks: "weakref.WeakValueDictionary[str, asyncio.Lock]" = weakref.WeakValueDictionary()
_tasks: set = set()


def is_valid_id(value: Optional[str]) -> bool:
    return bool(value and _UUID.match(value))


def lock_for(session_id: str) -> asyncio.Lock:
    """One lock per session so two quick messages are handled in order."""
    lock = _locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _locks[session_id] = lock
    return lock


def _key(session_id: str) -> str:
    return f"chat:session:{session_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_session(session_id: str, user_id: str, language: str = "english") -> dict:
    return {
        "session_id": session_id,
        "user_id": str(user_id),
        "language": language,
        "booking_confirmed": False,
        "messages": [],
        "context": {},
        "last_intent": None,
        "created_at": _now(),
        "updated_at": _now(),
    }


# -------------------------------------------------------------------- storage


def _fetch(session_id: str) -> Optional[dict]:
    rows = db.table("chat_sessions").select("*").eq("session_id", session_id) \
        .limit(1).execute().data
    return rows[0] if rows else None


async def load(session_id: str) -> Optional[dict]:
    """Live session from the cache, else the saved copy; None if neither."""
    hit = await cache_get(_key(session_id))
    if hit:
        return hit
    try:
        row = await asyncio.to_thread(_fetch, session_id)
    except Exception as e:
        logger.warning("Loading saved session failed: %s", type(e).__name__)
        return None
    if not row:
        return None
    session = {
        "session_id": row["session_id"],
        "user_id": str(row["user_id"]) if row.get("user_id") else None,
        "language": row.get("language") or "english",
        "booking_confirmed": bool(row.get("booking_confirmed")),
        "messages": row.get("messages") or [],
        "context": row.get("context") or {},
        "last_intent": row.get("last_intent"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }
    await cache_set(_key(session_id), session, SESSION_TTL)
    return session


def _upsert(session: dict) -> None:
    db.table("chat_sessions").upsert({
        "session_id": session["session_id"],
        "user_id": session["user_id"],
        "language": session["language"],
        "booking_confirmed": session["booking_confirmed"],
        "messages": session["messages"],
        "context": session["context"],
        "last_intent": session["last_intent"],
        "updated_at": session["updated_at"],
    }, on_conflict="session_id").execute()


def _persist_in_background(session: dict) -> None:
    async def run():
        try:
            await asyncio.to_thread(_upsert, dict(session))
        except Exception as e:
            logger.warning("Persisting chat session failed: %s", type(e).__name__)

    try:
        task = asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        return
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def save(session: dict) -> None:
    session["updated_at"] = _now()
    session["messages"] = session["messages"][-MAX_MESSAGES:]
    await cache_set(_key(session["session_id"]), session, SESSION_TTL)
    _persist_in_background(session)


def _delete_row(session_id: str) -> None:
    db.table("chat_sessions").delete().eq("session_id", session_id).execute()


async def clear(session: dict) -> None:
    """The user's DELETE: remove the live copy and the saved copy. (Sessions that
    simply expire keep their saved copy as history; this is the explicit wipe.)"""
    sid = session["session_id"]
    await cache_delete(_key(sid))
    try:
        await asyncio.to_thread(_delete_row, sid)
    except Exception as e:
        logger.warning("Deleting saved chat session failed: %s", type(e).__name__)
