"""
Middleware and auth dependencies for Obii Cabs API.

Two ASGI middlewares, applied to every request:
  * IPBlockMiddleware — 403 if the caller's IP is active in `blocked_ips`
  * JWTAuthMiddleware — 401 on any non-public route without a valid access token

Plus the dependencies handlers use to read the authenticated caller:
  * get_current_user — the full `users` row for the token subject
  * require_owner    — same, but 403 unless the caller is the business owner
"""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.database import db
from app.core.security import verify_token

# Routes reachable without a token. Everything else needs a Bearer access token.
PUBLIC_PATHS = {
    "/",
    "/health",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
    "/openapi.json",
    "/favicon.ico",
}
PUBLIC_PREFIXES = ("/api/auth",)


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def get_client_ip(request: Request) -> str:
    """
    Real caller IP. Behind Render/Vercel/nginx the socket peer is the proxy, so
    prefer the forwarded headers and take the left-most (original client) entry.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    real_ip = request.headers.get("x-real-ip")
    if real_ip and real_ip.strip():
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------- IP blocking

# Checking `blocked_ips` on every request would mean a Supabase round-trip per
# request, so results are cached briefly. block_ip() drops the entry so a fresh
# block takes effect immediately rather than after the TTL.
_BLOCK_CACHE_TTL = timedelta(seconds=60)
_block_cache: dict[str, tuple[bool, datetime]] = {}


def invalidate_ip_cache(ip: Optional[str] = None) -> None:
    if ip is None:
        _block_cache.clear()
    else:
        _block_cache.pop(ip, None)


def _query_ip_blocked(ip: str) -> bool:
    result = (
        db.table("blocked_ips")
        .select("id")
        .eq("ip_address", ip)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return bool(result.data)


async def is_ip_blocked(ip: str) -> bool:
    if ip == "unknown":
        return False

    now = datetime.utcnow()
    cached = _block_cache.get(ip)
    if cached and now < cached[1]:
        return cached[0]

    try:
        # supabase-py is sync; keep it off the event loop.
        blocked = await run_in_threadpool(_query_ip_blocked, ip)
    except Exception:
        # Fail open. If Supabase is unreachable, blocking every caller would
        # turn a database blip into a full outage; the blocklist is a spam
        # control, not the primary authorization boundary.
        return False

    _block_cache[ip] = (blocked, now + _BLOCK_CACHE_TTL)
    return blocked


class IPBlockMiddleware(BaseHTTPMiddleware):
    """Reject every request from a blocked IP with 403."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        ip = get_client_ip(request)
        request.state.client_ip = ip

        if await is_ip_blocked(ip):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Access blocked. Contact support."},
            )

        return await call_next(request)


# ------------------------------------------------------------------ JWT guard


def _unauthorized(detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"detail": detail},
        headers={"WWW-Authenticate": "Bearer"},
    )


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """
    Validate the Bearer access token on every non-public route and stash the
    decoded payload on request.state for get_current_user to pick up.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # CORS preflight never carries an Authorization header.
        if request.method == "OPTIONS" or is_public_path(request.url.path):
            return await call_next(request)

        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            return _unauthorized("Not authenticated. Bearer token required.")

        payload = verify_token(token.strip())
        if not payload:
            return _unauthorized("Invalid or expired token")

        # Refresh tokens are only valid at /api/auth/refresh, never as credentials.
        if payload.get("type") != "access":
            return _unauthorized("Access token required")

        if not payload.get("sub"):
            return _unauthorized("Malformed token payload")

        request.state.token_payload = payload
        request.state.user_id = payload["sub"]

        return await call_next(request)


# ----------------------------------------------------------- Dependencies

# auto_error=False so the middleware's message wins; this exists mainly to put
# the Authorize button in Swagger UI.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


def _fetch_user(user_id: str) -> Optional[dict]:
    result = (
        db.table("users").select("*").eq("id", user_id).limit(1).execute()
    )
    return result.data[0] if result.data else None


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """
    The `users` row for the caller. Normally the token was already verified by
    JWTAuthMiddleware; the fallback re-verifies so the dependency is still
    correct if used on a public path or with the middleware disabled.
    """
    payload = getattr(request.state, "token_payload", None)

    if payload is None:
        if credentials is None or not credentials.credentials:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Not authenticated. Bearer token required.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        payload = verify_token(credentials.credentials)
        if not payload or payload.get("type") != "access":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user = await run_in_threadpool(_fetch_user, user_id)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not reach the database. Try again.",
        )

    if not user:
        # Valid signature, but the account is gone (deleted between issue and use).
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


def normalize_mobile(value: Optional[str]) -> str:
    """
    Reduce an Indian mobile number to its bare last 10 digits.

    The OTP flow stores 10 digits ("7499313125") while OWNER_PHONE is normally
    written with a country code ("+917499313125"), so a plain string compare
    never matches. Stripping to the last 10 digits also absorbs "0" prefixes,
    spaces and dashes.

    Returns "" when there are fewer than 10 digits, so a blank or malformed
    config value can never match a real user.
    """
    digits = "".join(ch for ch in (value or "") if ch.isdigit())
    if len(digits) < 10:
        return ""
    return digits[-10:]


def is_owner(user: dict) -> bool:
    """
    The `users` table has no role column, so owner identity comes from
    OWNER_PHONE / OWNER_EMAIL in the environment. Both unset means nobody is
    owner and the owner-only routes stay closed — deliberately fail-closed.
    """
    owner_phone = normalize_mobile(settings.OWNER_PHONE)
    owner_email = (settings.OWNER_EMAIL or "").strip().lower()

    if owner_phone and normalize_mobile(user.get("mobile")) == owner_phone:
        return True
    if owner_email and (user.get("email") or "").strip().lower() == owner_email:
        return True
    return False


async def require_owner(user: dict = Depends(get_current_user)) -> dict:
    if not is_owner(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access required",
        )
    return user
