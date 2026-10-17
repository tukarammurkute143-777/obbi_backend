"""
Storage and workflow for blogs (`blogs` table).

Status flow:  draft --publish--> published        (owner only, the ONLY way)
              draft/rejected --publish--> published
              draft/published --reject--> rejected
Nothing in this module publishes on its own; only publish_blog() sets
status='published', and the routes that call it are owner-only.

Published blogs are served publicly and cached for an hour. Any change to a
blog bumps a version number that is part of every cache key, so the next read
rebuilds from the database (no need to enumerate keys).
"""

import asyncio
import logging
import re
import secrets
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from app.core.cache import cache_get, cache_set
from app.core.database import db

logger = logging.getLogger("blog_service")

CACHE_TTL = 3600
VERSION_KEY = "blogs:version"
STATUSES = ("draft", "published", "rejected")

SUMMARY_COLUMNS = (
    "id,title,slug,meta_description,blog_type,target_keyword,word_count,"
    "keyword_density,tags,status,confidence_score,generated_by,published_at,"
    "created_at,updated_at"
)
PUBLIC_LIST_COLUMNS = "id,title,slug,meta_description,blog_type,tags,word_count,published_at"
PUBLIC_COLUMNS = PUBLIC_LIST_COLUMNS + ",content,updated_at"

_UUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class BlogError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _db_error(what: str, e: Exception) -> BlogError:
    logger.error("%s failed: %s", what, type(e).__name__)
    return BlogError(503, "Database abhi available nahi hai.")


def is_valid_id(value: str) -> bool:
    return bool(_UUID.match(value or ""))


# ------------------------------------------------------------ text utilities

_SCRIPT = re.compile(r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>",
                     re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"</?[a-zA-Z!][^>]*>")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_BAD_LINK = re.compile(r"\]\(\s*(javascript|data|vbscript):[^)]*\)", re.IGNORECASE)


def clean_markdown(text: str) -> str:
    """
    Markdown for a public page: raw HTML, images and script-scheme links are
    removed, so whatever renders it cannot be made to run owner- or
    model-supplied markup. Links, headings, lists and emphasis are kept.
    """
    text = _SCRIPT.sub("", text or "")
    text = _TAG.sub("", text)
    text = _IMAGE.sub("", text)
    text = _BAD_LINK.sub("](#)", text)
    return text.strip()


def slugify(text: str, max_len: int = 90) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].strip("-") or "blog"


_WORD = re.compile(r"[A-Za-z0-9ऀ-ॿ][A-Za-z0-9ऀ-ॿ'’]*")
_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)


def _plain(text: str) -> str:
    """Lower-cased text with markdown punctuation collapsed to single spaces,
    so 'Pune-to-Shirdi' and '**Pune to Shirdi**' both match 'pune to shirdi'."""
    text = re.sub(r"\]\([^)]*\)", " ", text)      # link targets
    return " ".join(re.sub(r"[^a-z0-9ऀ-ॿ]+", " ", text.lower()).split())


def count_words(content: str) -> int:
    body = re.sub(r"\]\([^)]*\)", " ", content)
    return len(_WORD.findall(body))


def count_keyword(content: str, keyword: str) -> int:
    kw = _plain(keyword)
    if not kw:
        return 0
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])", _plain(content)))


def keyword_density(content: str, keyword: str) -> float:
    """
    Share of the article's words that belong to the keyword phrase:
    occurrences x words-in-phrase / total words. Phrase-weighted on purpose: a
    4-word keyword at plain "occurrences / words" of 3% would have to appear 36
    times in 1,200 words, which is keyword stuffing.
    """
    total = count_words(content)
    kw_words = len(_plain(keyword).split())
    if not total or not kw_words:
        return 0.0
    return round(count_keyword(content, keyword) * kw_words / total, 4)


def headings(content: str, level: Optional[int] = None) -> list[str]:
    return [m.group(2).strip() for m in _HEADING.finditer(content)
            if level is None or len(m.group(1)) == level]


def first_paragraph(content: str) -> str:
    for block in re.split(r"\n\s*\n", content.strip()):
        block = block.strip()
        if block and not block.startswith("#"):
            return block
    return ""


# ------------------------------------------------------------------ cache

async def _version() -> int:
    v = await cache_get(VERSION_KEY)
    return v if isinstance(v, int) else 0


async def invalidate_public_cache() -> None:
    await cache_set(VERSION_KEY, await _version() + 1, 30 * 24 * 3600)


# ------------------------------------------------------------- owner: create


def _slug_taken(slug: str) -> bool:
    return bool(db.table("blogs").select("id").eq("slug", slug).limit(1)
                .execute().data)


def _insert(fields: dict) -> dict:
    base = fields["slug"]
    for attempt in range(4):
        candidate = base if attempt == 0 else f"{base[:80]}-{secrets.token_hex(2)}"
        if attempt == 0 and _slug_taken(candidate):
            continue
        try:
            return db.table("blogs").insert({**fields, "slug": candidate}) \
                .execute().data[0]
        except Exception as e:
            # A concurrent insert can still win the unique slug; try a new one.
            if "duplicate" in str(e).lower() or "unique" in str(e).lower():
                continue
            raise
    raise RuntimeError("could not find a free slug")


async def create_draft(fields: dict) -> dict:
    """Insert a blog as status='draft'. Always a draft, whatever the caller says."""
    row = {**fields, "status": "draft", "published_at": None, "generated_by": "ai"}
    try:
        return await asyncio.to_thread(_insert, row)
    except Exception as e:
        raise _db_error("create_draft", e)


# ---------------------------------------------------------------- owner: read


def _list(status: Optional[str], limit: int, offset: int) -> list:
    q = db.table("blogs").select(SUMMARY_COLUMNS)
    if status:
        q = q.eq("status", status)
    return q.order("created_at", desc=True).range(offset, offset + limit - 1) \
        .execute().data or []


def _counts() -> dict:
    out = {}
    for s in STATUSES:
        out[s] = db.table("blogs").select("id", count="exact").eq("status", s) \
            .limit(1).execute().count or 0
    return out


async def list_blogs(status: Optional[str], limit: int, offset: int) -> dict:
    if status and status not in STATUSES:
        raise BlogError(400, f"status must be one of: {', '.join(STATUSES)}.")
    try:
        rows = await asyncio.to_thread(_list, status, limit, offset)
        counts = await asyncio.to_thread(_counts)
    except Exception as e:
        raise _db_error("list_blogs", e)
    # `counts.draft` is the owner's "needs review" number for the dashboard.
    return {"counts": counts, "total": counts.get(status) if status else sum(counts.values()),
            "blogs": rows}


def _get(blog_id: str) -> Optional[dict]:
    rows = db.table("blogs").select("*").eq("id", blog_id).limit(1).execute().data
    return rows[0] if rows else None


async def get_blog(blog_id: str) -> dict:
    if not is_valid_id(blog_id):
        raise BlogError(404, "Blog nahi mila.")
    try:
        row = await asyncio.to_thread(_get, blog_id)
    except Exception as e:
        raise _db_error("get_blog", e)
    if not row:
        raise BlogError(404, "Blog nahi mila.")
    return row


# ------------------------------------------------------------- owner: change


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _transition(blog_id: str, allowed_from: tuple, fields: dict) -> Optional[dict]:
    """Conditional update: only applies if the row is still in an allowed
    status, so two quick clicks (or two owners) cannot double-apply."""
    rows = (db.table("blogs").update({**fields, "updated_at": _now()})
            .eq("id", blog_id).in_("status", list(allowed_from)).execute().data)
    return rows[0] if rows else None


async def _change(blog_id: str, allowed_from: tuple, fields: dict, refusal: str) -> dict:
    if not is_valid_id(blog_id):
        raise BlogError(404, "Blog nahi mila.")
    try:
        row = await asyncio.to_thread(_transition, blog_id, allowed_from, fields)
        if row is None:
            exists = await asyncio.to_thread(_get, blog_id)
            raise BlogError(409 if exists else 404,
                            refusal if exists else "Blog nahi mila.")
    except BlogError:
        raise
    except Exception as e:
        raise _db_error("blog status change", e)
    await invalidate_public_cache()
    return row


async def publish_blog(blog_id: str) -> dict:
    """The only code path that sets status='published'."""
    return await _change(
        blog_id, ("draft", "rejected"),
        {"status": "published", "published_at": _now()},
        "Yeh blog pehle se published hai.")


async def reject_blog(blog_id: str) -> dict:
    return await _change(
        blog_id, ("draft", "published"),
        {"status": "rejected", "published_at": None},
        "Yeh blog pehle se rejected hai.")


async def update_blog(blog_id: str, title: Optional[str], content: Optional[str]) -> dict:
    current = await get_blog(blog_id)
    fields: dict = {}
    if title is not None:
        title = " ".join(title.split())
        if not title:
            raise BlogError(400, "title khaali nahi ho sakta.")
        fields["title"] = title[:300]
    if content is not None:
        content = clean_markdown(content)
        if not content:
            raise BlogError(400, "content khaali nahi ho sakta.")
        fields["content"] = content
        # Keep the stored SEO numbers honest after an edit.
        fields["word_count"] = count_words(content)
        fields["keyword_density"] = keyword_density(
            content, current.get("target_keyword") or "")
    if not fields:
        raise BlogError(400, "title ya content do.")

    try:
        rows = await asyncio.to_thread(
            lambda: db.table("blogs").update({**fields, "updated_at": _now()})
            .eq("id", blog_id).execute().data)
    except Exception as e:
        raise _db_error("update_blog", e)
    if not rows:
        raise BlogError(404, "Blog nahi mila.")
    if rows[0]["status"] == "published":
        await invalidate_public_cache()
    return rows[0]


async def delete_blog(blog_id: str) -> None:
    """Drafts and rejected blogs only; a published blog must be rejected first."""
    if not is_valid_id(blog_id):
        raise BlogError(404, "Blog nahi mila.")
    try:
        current = await asyncio.to_thread(_get, blog_id)
        if not current:
            raise BlogError(404, "Blog nahi mila.")
        if current["status"] == "published":
            raise BlogError(409, "Published blog delete nahi ho sakta. "
                                 "Pehle reject (unpublish) karo.")
        # Status repeated in the DELETE so a publish that lands in between
        # cannot be deleted from under the readers.
        await asyncio.to_thread(
            lambda: db.table("blogs").delete().eq("id", blog_id)
            .neq("status", "published").execute())
    except BlogError:
        raise
    except Exception as e:
        raise _db_error("delete_blog", e)


# --------------------------------------------------------------- public reads


def _public_list(limit: int, offset: int) -> list:
    return (db.table("blogs").select(PUBLIC_LIST_COLUMNS).eq("status", "published")
            .order("published_at", desc=True).range(offset, offset + limit - 1)
            .execute().data or [])


async def public_list(limit: int, offset: int) -> dict:
    key = f"blogs:list:{await _version()}:{limit}:{offset}"
    hit = await cache_get(key)
    if hit is not None:
        return hit
    try:
        rows = await asyncio.to_thread(_public_list, limit, offset)
    except Exception as e:
        raise _db_error("public_list", e)
    result = {"blogs": rows, "limit": limit, "offset": offset}
    await cache_set(key, result, CACHE_TTL)
    return result


def _public_get(slug: str) -> Optional[dict]:
    rows = (db.table("blogs").select(PUBLIC_COLUMNS).eq("slug", slug)
            .eq("status", "published").limit(1).execute().data)
    return rows[0] if rows else None


async def public_get(slug: str) -> dict:
    if not SLUG_RE.match(slug or "") or len(slug) > 255:
        raise BlogError(404, "Blog nahi mila.")
    key = f"blogs:slug:{await _version()}:{slug}"
    hit = await cache_get(key)
    if hit is not None:
        return hit
    try:
        row = await asyncio.to_thread(_public_get, slug)
    except Exception as e:
        raise _db_error("public_get", e)
    if not row:
        raise BlogError(404, "Blog nahi mila.")
    await cache_set(key, row, CACHE_TTL)
    return row
