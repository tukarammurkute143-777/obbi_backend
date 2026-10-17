"""Tavily web search with a 1-hour cache. Returns None when search is unavailable."""

import hashlib
import logging
from typing import Optional

import httpx

from app.core.cache import cache_get, cache_set
from app.core.config import settings

logger = logging.getLogger("web_search")

TAVILY_URL = "https://api.tavily.com/search"
TIMEOUT = 8.0
CACHE_TTL = 3600


async def search(query: str, max_results: int = 5) -> Optional[list[dict]]:
    """[{'title', 'url', 'content'}], [] for no hits, or None if the search failed."""
    api_key = settings.TAVILY_API_KEY.strip()
    if not api_key:
        return None

    key = "websearch:" + hashlib.sha256(f"{query}|{max_results}".encode()).hexdigest()
    hit = await cache_get(key)
    if hit is not None:
        return hit

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(
                TAVILY_URL, headers={"Authorization": f"Bearer {api_key}"},
                json={"query": query, "search_depth": "basic",
                      "max_results": max_results, "include_answer": False})
        if resp.status_code != 200:
            logger.warning("Tavily returned HTTP %s", resp.status_code)
            return None
        raw = resp.json().get("results") or []
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("Tavily search failed: %s", type(e).__name__)
        return None

    results = [{"title": str(r.get("title") or ""), "url": str(r.get("url") or ""),
                "content": str(r.get("content") or "")}
               for r in raw if isinstance(r, dict)]
    await cache_set(key, results, CACHE_TTL)
    return results
