"""
Route Agent: distance, time and route options via the Google Maps API.

Every public method returns a dict and never raises:
  success: {'success': True, ...data}
  failure: {'success': False, 'status': <http status>, 'message': <safe text>}
Google's raw error text is logged, not returned.

Results are cached for 24 hours (Redis, with an in-memory fallback). Failures
are never cached, so a transient Google error does not stick for a day.
"""

import asyncio
import logging
import re
from typing import Optional

import googlemaps
from googlemaps.exceptions import ApiError, Timeout, TransportError

from app.core.cache import cache_get, cache_set
from app.core.config import settings

logger = logging.getLogger("route_agent")

CACHE_TTL = 24 * 3600
MAX_ROUTES = 3
REQUEST_TIMEOUT = 8  # seconds

_TAGS = re.compile(r"<[^>]+>")


def _fail(status: int, message: str) -> dict:
    return {"success": False, "status": status, "message": message}


def _norm(place: str) -> str:
    return " ".join((place or "").split())


def _cache_key(kind: str, origin: str, destination: str) -> str:
    return f"route:{kind}:{origin.lower()}|{destination.lower()}"


def _strip_html(text: str) -> str:
    return " ".join(_TAGS.sub(" ", text or "").replace("&nbsp;", " ").split())


def _km(meters: int) -> float:
    return round(meters / 1000, 1)


def _minutes(seconds: int) -> int:
    return round(seconds / 60)


class RouteAgent:
    def __init__(self) -> None:
        self._client: Optional[googlemaps.Client] = None

    def _maps(self) -> Optional[googlemaps.Client]:
        if self._client is None:
            if not settings.GOOGLE_MAPS_API_KEY.strip():
                return None
            self._client = googlemaps.Client(
                key=settings.GOOGLE_MAPS_API_KEY,
                timeout=REQUEST_TIMEOUT,
                retry_timeout=REQUEST_TIMEOUT,
            )
        return self._client

    # ------------------------------------------------------------ plumbing

    async def _call(self, fn, *args, **kwargs):
        """
        Run a blocking googlemaps call off the event loop.
        Returns (result, None) or (None, failure_dict).
        """
        try:
            client = self._maps()
        except ValueError:
            # googlemaps rejects any key that does not start with "AIza".
            logger.error("GOOGLE_MAPS_API_KEY is malformed")
            return None, _fail(503, "Route service abhi available nahi hai.")
        if client is None:
            logger.error("GOOGLE_MAPS_API_KEY is not set")
            return None, _fail(503, "Route service abhi available nahi hai.")
        try:
            return await asyncio.to_thread(getattr(client, fn), *args, **kwargs), None
        except ApiError as e:
            logger.error("Google Maps %s ApiError: %s %s", fn, e.status,
                         getattr(e, "message", ""))
            if e.status in ("REQUEST_DENIED", "OVER_QUERY_LIMIT",
                            "OVER_DAILY_LIMIT", "INVALID_REQUEST"):
                return None, _fail(503, "Route service abhi available nahi hai.")
            return None, _fail(502, "Route service se jawab nahi mila.")
        except (Timeout, TransportError) as e:
            logger.error("Google Maps %s network failure: %s", fn, type(e).__name__)
            return None, _fail(502, "Route service se jawab nahi mila.")
        except Exception as e:
            logger.exception("Google Maps %s unexpected error: %s", fn, type(e).__name__)
            return None, _fail(502, "Route service se jawab nahi mila.")

    @staticmethod
    def _validate(origin: str, destination: str) -> Optional[dict]:
        if not (2 <= len(origin) <= 200 and 2 <= len(destination) <= 200):
            return _fail(400, "Valid origin aur destination daalo.")
        return None

    async def _cached(self, kind: str, origin: str, destination: str,
                      compute, use_cache: bool = True) -> dict:
        origin, destination = _norm(origin), _norm(destination)
        invalid = self._validate(origin, destination)
        if invalid:
            return invalid

        key = _cache_key(kind, origin, destination)
        hit = await cache_get(key) if use_cache else None
        if hit is not None:
            return {**hit, "cached": True}

        try:
            result = await compute(origin, destination)
        except Exception as e:  # last-resort guard: this class never raises
            logger.exception("Route %s crashed: %s", kind, type(e).__name__)
            return _fail(500, "Route nikalne mein dikkat aayi.")

        if result.get("success"):
            await cache_set(key, result, CACHE_TTL)
        return {**result, "cached": False}

    # --------------------------------------------------------- public API

    async def get_distance_and_time(self, origin: str, destination: str,
                                    use_cache: bool = True) -> dict:
        """{'success', 'distance_km', 'duration_min', 'duration_text'}"""
        return await self._cached("dt", origin, destination, self._distance_time,
                                  use_cache)

    async def get_route_info(self, origin: str, destination: str,
                             use_cache: bool = True) -> dict:
        """Best route with start/end addresses, summary and turn-by-turn waypoints."""
        async def compute(o, d):
            routes = await self._directions(o, d, alternatives=False)
            if isinstance(routes, dict):
                return routes
            return {"success": True, **self._summarize(routes[0], with_steps=True)}

        return await self._cached("info", origin, destination, compute, use_cache)

    async def get_multiple_routes(self, origin: str, destination: str,
                                  use_cache: bool = True) -> dict:
        """Up to 3 route options, shortest travel time first."""
        async def compute(o, d):
            routes = await self._directions(o, d, alternatives=True)
            if isinstance(routes, dict):
                return routes
            options = sorted(
                (self._summarize(r, with_steps=False) for r in routes),
                key=lambda r: r["duration_min"],
            )[:MAX_ROUTES]
            return {"success": True, "count": len(options), "routes": options}

        return await self._cached("multi", origin, destination, compute, use_cache)

    # ------------------------------------------------------------ internals

    async def _distance_time(self, origin: str, destination: str) -> dict:
        data, err = await self._call(
            "distance_matrix", [origin], [destination],
            mode="driving", units="metric", region="in",
        )
        if err:
            return err
        try:
            element = data["rows"][0]["elements"][0]
        except (KeyError, IndexError, TypeError):
            logger.error("Malformed distance_matrix response")
            return _fail(502, "Route service se galat jawab mila.")

        if element.get("status") in ("NOT_FOUND", "ZERO_RESULTS"):
            return _fail(404, "Is route ka koi rasta nahi mila.")
        if element.get("status") != "OK":
            logger.error("distance_matrix element status %s", element.get("status"))
            return _fail(502, "Route service se jawab nahi mila.")

        return {
            "success": True,
            "distance_km": _km(element["distance"]["value"]),
            "duration_min": _minutes(element["duration"]["value"]),
            "duration_text": element["duration"]["text"],
        }

    async def _directions(self, origin: str, destination: str, alternatives: bool):
        """List of raw routes, or a failure dict."""
        data, err = await self._call(
            "directions", origin, destination,
            mode="driving", alternatives=alternatives, units="metric", region="in",
        )
        if err:
            return err
        if not data:  # empty list == ZERO_RESULTS / NOT_FOUND
            return _fail(404, "Is route ka koi rasta nahi mila.")
        return data

    @staticmethod
    def _summarize(route: dict, with_steps: bool) -> dict:
        legs = route.get("legs") or [{}]
        first, last = legs[0], legs[-1]
        meters = sum(l.get("distance", {}).get("value", 0) for l in legs)
        seconds = sum(l.get("duration", {}).get("value", 0) for l in legs)

        out = {
            "summary": route.get("summary", ""),
            "distance_km": _km(meters),
            "duration_min": _minutes(seconds),
            "duration_text": first.get("duration", {}).get("text", "")
            if len(legs) == 1 else f"{_minutes(seconds)} mins",
            "start_address": first.get("start_address", ""),
            "end_address": last.get("end_address", ""),
            "warnings": route.get("warnings", []),
        }
        if with_steps:
            steps = [s for leg in legs for s in leg.get("steps", [])]
            out["waypoints"] = [
                {
                    "instruction": _strip_html(s.get("html_instructions", "")),
                    "distance_km": _km(s.get("distance", {}).get("value", 0)),
                    "duration_min": _minutes(s.get("duration", {}).get("value", 0)),
                    "location": s.get("end_location"),
                }
                for s in steps
            ]
        return out
