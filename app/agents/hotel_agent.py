"""
Hotel Agent: finds hotels anywhere in India using the Tavily search API.

Tavily returns web search results (title, url, text snippet), not structured
hotel records. Name, rating, price and amenities are therefore extracted from
the snippet text on a best-effort basis: a field is None / empty when the page
snippet did not mention it. Prices and ratings are indicative, not live rates.

Every public method returns a dict and never raises:
  success: {'success': True, 'hotels': [...], ...}
  failure: {'success': False, 'status': <http status>, 'message': <safe text>}
Results are cached for 6 hours; failures are never cached.
"""

import logging
import re
from datetime import date
from typing import Optional

import httpx

from app.core.cache import cache_get, cache_set
from app.core.config import settings

logger = logging.getLogger("hotel_agent")

TAVILY_URL = "https://api.tavily.com/search"
TAVILY_TIMEOUT = 10.0
CACHE_TTL = 6 * 3600
MAX_HOTELS = 5
FETCH_RESULTS = 10  # over-fetch: some hits are listicles/articles and get dropped

_DEST = re.compile(r"^[\w\s.,'\-]{2,100}$", re.UNICODE)

_BOOKING_DOMAINS = (
    "booking.com", "makemytrip.com", "goibibo.com", "agoda.com", "tripadvisor.",
    "cleartrip.com", "expedia.", "yatra.com", "trivago.", "oyorooms.com",
    "airbnb.", "easemytrip.com", "hotels.com", "ixigo.com",
)

# "Top 10 hotels in X", "Best hotels in X" etc: an article, not one hotel.
_LISTICLE = re.compile(
    r"\b(top|best)\b.*\bhotels?\b|\bhotels?\b.*\b(in|near|around)\b|\b\d+\s+(best|top)\b",
    re.IGNORECASE,
)
_TITLE_SPLIT = re.compile(r"\s+[|\-–—:]\s+")

_RATING = re.compile(
    r"(?<![\d.])([1-5](?:\.\d)?)\s*(?:/\s*5\b|out of 5|stars?\b|★)|rated\s+([1-5](?:\.\d)?)",
    re.IGNORECASE,
)
_PRICE = re.compile(
    r"(?:₹|Rs\.?|INR)\s*([\d,]{3,7})(?:\s*(?:-|–|to)\s*(?:₹|Rs\.?|INR)?\s*([\d,]{3,7}))?",
    re.IGNORECASE,
)

_AMENITIES = {
    "Free WiFi": r"wi-?fi",
    "Swimming pool": r"\bpool\b",
    "Breakfast": r"breakfast",
    "Parking": r"parking",
    "Air conditioning": r"\ba/?c\b|air[- ]condition",
    "Spa": r"\bspa\b",
    "Gym": r"\bgym\b|fitness",
    "Restaurant": r"restaurant",
    "Bar": r"\bbar\b",
    "Room service": r"room service",
    "Airport shuttle": r"airport (shuttle|transfer|pickup)",
    "Pet friendly": r"pet[- ]friendly",
}


def _fail(status: int, message: str) -> dict:
    return {"success": False, "status": status, "message": message}


def _clean_name(title: str) -> str:
    return _TITLE_SPLIT.split(title.strip())[0].strip(" .,-")[:120]


def _price_value(raw: str) -> Optional[int]:
    try:
        value = int(raw.replace(",", ""))
    except ValueError:
        return None
    return value if 200 <= value <= 500000 else None  # drops years, phone digits


def _extract_price(text: str) -> Optional[str]:
    for m in _PRICE.finditer(text):
        low = _price_value(m.group(1))
        if low is None:
            continue
        high = _price_value(m.group(2)) if m.group(2) else None
        if high and high > low:
            return f"₹{low:,} - ₹{high:,}"
        return f"₹{low:,}"
    return None


def _extract_rating(text: str) -> Optional[float]:
    m = _RATING.search(text)
    if not m:
        return None
    return float(m.group(1) or m.group(2))


def _extract_amenities(text: str) -> list[str]:
    return [name for name, pat in _AMENITIES.items()
            if re.search(pat, text, re.IGNORECASE)]


def _booking_url(url: str) -> Optional[str]:
    host = re.sub(r"^https?://", "", url.lower()).split("/")[0]
    return url if any(d in host for d in _BOOKING_DOMAINS) else None


class HotelAgent:
    # ---------------------------------------------------------- public API

    async def search_hotels(
        self,
        destination: str,
        check_in: Optional[str] = None,
        check_out: Optional[str] = None,
        guests: int = 1,
    ) -> dict:
        """
        Top hotels near popular attractions. check_in / check_out (YYYY-MM-DD)
        and guests are validated and echoed back, but web results are not
        date-specific, so they do not change what is returned.
        """
        error = self._validate_stay(check_in, check_out, guests)
        if error:
            return error
        result = await self._search(
            "all", destination, "best hotels in {d} near popular attractions"
        )
        if result.get("success"):
            result = {**result, "check_in": check_in, "check_out": check_out,
                      "guests": guests}
        return result

    async def get_budget_hotels(self, destination: str) -> dict:
        return await self._search("budget", destination, "budget hotels in {d} India")

    async def get_premium_hotels(self, destination: str) -> dict:
        return await self._search("premium", destination, "luxury hotels in {d} India")

    # ------------------------------------------------------------ internals

    @staticmethod
    def _validate_stay(check_in, check_out, guests) -> Optional[dict]:
        """A failure dict, or None when the inputs are fine."""
        if not isinstance(guests, int) or not 1 <= guests <= 20:
            return _fail(400, "Guests 1 se 20 ke beech hone chahiye.")
        try:
            d_in = date.fromisoformat(check_in) if check_in else None
            d_out = date.fromisoformat(check_out) if check_out else None
        except ValueError:
            return _fail(400, "Date YYYY-MM-DD format mein daalo.")
        if d_in and d_in < date.today():
            return _fail(400, "Check-in date past mein nahi ho sakti.")
        if d_in and d_out and d_out <= d_in:
            return _fail(400, "Check-out date check-in ke baad honi chahiye.")
        return None

    async def _search(self, kind: str, destination: str, template: str) -> dict:
        destination = " ".join((destination or "").split())
        if not _DEST.match(destination):
            return _fail(400, "Valid destination daalo.")

        key = f"hotels:{kind}:{destination.lower()}"
        hit = await cache_get(key)
        if hit is not None:
            return {**hit, "cached": True}

        try:
            hotels, err = await self._query(template.format(d=destination), destination)
        except Exception as e:  # last-resort guard: this class never raises
            logger.exception("Hotel search crashed: %s", type(e).__name__)
            return _fail(503, "Hotel service abhi available nahi hai.")
        if err:
            return err
        if not hotels:
            return _fail(404, f"{destination} ke liye koi hotel nahi mila.")

        result = {
            "success": True,
            "destination": destination,
            "type": kind,
            "count": len(hotels),
            "hotels": hotels,
        }
        await cache_set(key, result, CACHE_TTL)
        return {**result, "cached": False}

    async def _query(self, query: str, destination: str):
        """(hotels, None) or (None, failure_dict)."""
        api_key = settings.TAVILY_API_KEY.strip()
        if not api_key:
            logger.error("TAVILY_API_KEY is not set")
            return None, _fail(503, "Hotel service abhi available nahi hai.")

        try:
            async with httpx.AsyncClient(timeout=TAVILY_TIMEOUT) as client:
                resp = await client.post(
                    TAVILY_URL,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "query": query,
                        "search_depth": "basic",
                        "max_results": FETCH_RESULTS,
                        "include_answer": False,
                    },
                )
        except httpx.HTTPError as e:
            logger.error("Tavily request failed: %s", type(e).__name__)
            return None, _fail(503, "Hotel service abhi available nahi hai.")

        if resp.status_code != 200:
            # 401/403 bad key, 429 quota, 5xx outage: all "temporarily unavailable"
            # to the caller; the status goes to the logs for us.
            logger.error("Tavily returned HTTP %s", resp.status_code)
            return None, _fail(503, "Hotel service abhi available nahi hai.")

        try:
            results = resp.json().get("results") or []
        except ValueError:
            logger.error("Tavily returned non-JSON body")
            return None, _fail(503, "Hotel service abhi available nahi hai.")

        return self._to_hotels(results, destination), None

    @staticmethod
    def _to_hotels(results: list, destination: str) -> list[dict]:
        singles, articles = [], []
        for r in results:
            if not isinstance(r, dict) or not r.get("title"):
                continue
            is_article = bool(_LISTICLE.search(r["title"]))
            (articles if is_article else singles).append((r, is_article))

        # Prefer pages about a single hotel; use article hits only to fill up
        # when Tavily returned few of those.
        hotels, seen = [], set()
        for r, is_article in singles + articles:
            name = _clean_name(r["title"])
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            text = f"{r['title']}. {r.get('content') or ''}"
            hotels.append({
                "name": name,
                "location": destination,
                "rating": _extract_rating(text),
                "price_range": _extract_price(text),
                "amenities": _extract_amenities(text),
                "booking_url": _booking_url(r.get("url") or ""),
                "source_url": r.get("url"),
                # True when the hit is a "best hotels in X" roundup rather than
                # one hotel's page, so `name` is the article title.
                "is_article": is_article,
            })
            if len(hotels) == MAX_HOTELS:
                break
        return hotels
