"""
Rate limiting (slowapi).

Limits are keyed on the caller's real IP (X-Forwarded-For aware), and scoped
per endpoint:
  * /api/auth/send-otp   → 3/hour   (decorator)
  * /api/auth/verify-otp → 5/hour   (decorator)
  * every other route    → 100/minute and 100/hour (default_limits, via SlowAPIMiddleware)
  * AI endpoints         → 10/hour (decorator)

Buckets are per user (JWT subject) when a valid token is sent, else per IP.

SlowAPIMiddleware skips any route carrying a @limiter.limit decorator, so the
OTP routes are governed by their own limit only — they are not also charged
against the 100/minute default.
"""

from fastapi import Request
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.middleware import get_client_ip
from app.core.security import verify_token

def user_or_ip_key(request: Request) -> str:
    """
    Rate-limit bucket: the JWT subject when the caller sent a valid access
    token, otherwise their IP. This runs before JWTAuthMiddleware, so the token
    is decoded here rather than read from request.state.
    """
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        payload = verify_token(token.strip())
        if payload and payload.get("type") == "access" and payload.get("sub"):
            return f"user:{payload['sub']}"
    return get_client_ip(request)


limiter = Limiter(
    key_func=user_or_ip_key,
    default_limits=[settings.RATE_LIMIT_GENERAL, settings.RATE_LIMIT_USER_HOUR],
    storage_uri=settings.RATE_LIMIT_STORAGE_URI,
)


def rate_limit_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    429 response for a tripped limit.

    Must stay sync: SlowAPIMiddleware calls handlers through sync_check_limits
    and silently falls back to slowapi's built-in handler if this is a
    coroutine function, which would discard the friendly message below.
    """
    limit = getattr(exc, "detail", "") or ""
    response = JSONResponse(
        status_code=429,
        content={
            "detail": f"Too many requests. Limit: {limit}. Thodi der baad try karo.",
            "limit": limit,
        },
    )
    # Adds X-RateLimit-* / Retry-After when the limit is known.
    view_limit = getattr(request.state, "view_rate_limit", None)
    if view_limit:
        response = limiter._inject_headers(response, view_limit)
    return response


__all__ = ["limiter", "rate_limit_handler", "RateLimitExceeded"]
