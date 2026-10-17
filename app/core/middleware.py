"""
Middleware and auth dependencies for Obii Cabs API.

Three ASGI middlewares, applied to every request:
  * IPBlockMiddleware — 403 if the caller's IP is active in `blocked_ips`
  * JWTAuthMiddleware — 401 on any non-public route without a valid access token
  * GuardrailsMiddleware — input checks on every request, output checks on AI replies

Plus the dependencies handlers use to read the authenticated caller:
  * get_current_user — the full `users` row for the token subject
  * require_owner    — same, but 403 unless the caller is the business owner
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import parse_qsl, urlencode

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.core.config import settings
from app.core.database import db
from app.core.guardrails import (
    INVALID_INPUT,
    input_guardrails,
    output_guardrails,
)
from app.core.security import verify_token

logger = logging.getLogger("guardrails")

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
# /api/blogs is public so search engines can read published posts.
PUBLIC_PREFIXES = ("/api/auth", "/api/blogs")


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
        .select("*")
        .eq("ip_address", ip)
        .eq("is_active", True)
        .execute()
    )
    # Filtered in Python rather than in the query so this keeps working before
    # the expires_at column exists. NULL expires_at means a permanent block.
    now = datetime.now(timezone.utc)
    for row in result.data or []:
        raw = row.get("expires_at")
        if not raw:
            return True
        try:
            expires = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            return True
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires > now:
            return True
    return False


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



# ----------------------------------------------------------------- Guardrails

# Never touched by guardrails.
GUARDRAIL_SKIP_PATHS = {"/health", "/docs", "/docs/oauth2-redirect", "/redoc",
                        "/openapi.json", "/favicon.ico"}
# Replies generated by an LLM; these also get output guardrails.
AI_PATH_PREFIXES = ("/api/safar/itinerary", "/api/safar/chat")
MAX_BODY_BYTES = 100_000

# Owner-only endpoints whose JSON body carries a whole article. `content` there
# gets its own (much larger) length limit and is exempt from the injection scan
# and entity-encoding, which would reject or corrupt ordinary prose ("select a
# hotel from the list", apostrophes). It is HTML-stripped when saved.
RICH_TEXT_PATHS = ("/api/dashboard/blogs",)
RICH_TEXT_FIELD = "content"
RICH_TEXT_MAX_CHARS = 60_000
RICH_TEXT_MAX_BODY_BYTES = 250_000


def _reject(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


class GuardrailsMiddleware:
    """
    Input guardrails on every request (query string + JSON body): reject SQL /
    prompt injection and over-long strings with 400, strip HTML and encode the
    rest. Output guardrails on AI endpoints: mask PII, filter content, flag low
    confidence. Pure ASGI so the sanitized body can be handed on to the route.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if (scope["type"] != "http" or scope["method"] == "OPTIONS"
                or path in GUARDRAIL_SKIP_PATHS):
            return await self.app(scope, receive, send)

        body = None
        try:
            rejection = self._check_query(scope)
            if not rejection and scope["method"] in ("POST", "PUT", "PATCH"):
                body, rejection = await self._check_body(scope, receive)
        except Exception as e:
            # A guardrail bug must not take the API down.
            logger.error("Input guardrails crashed: %s", type(e).__name__)
            return await self.app(scope, receive, send)

        if rejection:
            return await rejection(scope, receive, send)

        if body is not None:
            sent = False

            async def replay():
                nonlocal sent
                if sent:
                    return {"type": "http.disconnect"}
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}

            receive = replay

        if path.startswith(AI_PATH_PREFIXES):
            send = self._output_filter(send)
        return await self.app(scope, receive, send)

    # ---- input ----

    @staticmethod
    def _violation(data) -> Optional[JSONResponse]:
        too_long = input_guardrails.find_length_violation(data)
        if too_long:
            field, limit = too_long
            return _reject(400, f"'{field}' is too long (max {limit} characters)")
        if input_guardrails.find_attack(data):
            return _reject(400, INVALID_INPUT)
        return None

    def _check_query(self, scope) -> Optional[JSONResponse]:
        raw = scope.get("query_string", b"").decode("utf-8", "replace")
        if not raw:
            return None
        pairs = parse_qsl(raw, keep_blank_values=True)
        bad = self._violation(dict(pairs))
        if bad:
            return bad
        scope["query_string"] = urlencode(
            [(k, input_guardrails.sanitize({k: v})[k]) for k, v in pairs]
        ).encode()
        return None

    async def _check_body(self, scope, receive):
        """(body to forward | None, rejection | None)"""
        rich = scope.get("path", "").startswith(RICH_TEXT_PATHS)
        limit = RICH_TEXT_MAX_BODY_BYTES if rich else MAX_BODY_BYTES
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                break
            size += len(message.get("body", b""))
            if size > limit:
                return None, _reject(413, "Request body too large")
            chunks.append(message.get("body", b""))
            if not message.get("more_body"):
                break
        raw = b"".join(chunks)

        if not raw or b"json" not in dict(scope["headers"]).get(b"content-type", b""):
            return raw, None
        try:
            data = json.loads(raw)
        except ValueError:
            return raw, None  # let FastAPI return its own 422

        article = None
        if rich and isinstance(data, dict) and isinstance(data.get(RICH_TEXT_FIELD), str):
            article = data.pop(RICH_TEXT_FIELD)
            if len(article) > RICH_TEXT_MAX_CHARS:
                return None, _reject(
                    400, f"'{RICH_TEXT_FIELD}' is too long (max {RICH_TEXT_MAX_CHARS} characters)")

        bad = self._violation(data)
        if bad:
            return None, bad

        data = input_guardrails.sanitize(data)
        if article is not None:
            data[RICH_TEXT_FIELD] = article
        body = json.dumps(data).encode()
        scope["headers"] = [
            (k, str(len(body)).encode() if k == b"content-length" else v)
            for k, v in scope["headers"]
        ]
        return body, None

    # ---- output ----

    @staticmethod
    def _output_filter(send):
        start, chunks = None, []

        async def wrapper(message):
            nonlocal start
            if message["type"] == "http.response.start":
                start = message
                return
            if message["type"] != "http.response.body" or start is None:
                return await send(message)

            chunks.append(message.get("body", b""))
            if message.get("more_body"):
                return
            body = b"".join(chunks)

            headers = dict(start["headers"])
            if start["status"] == 200 and b"json" in headers.get(b"content-type", b""):
                try:
                    body = json.dumps(
                        output_guardrails.process(json.loads(body)),
                        ensure_ascii=False,
                    ).encode()
                except Exception as e:
                    logger.error("Output guardrails failed: %s", type(e).__name__)
            start["headers"] = [
                (k, str(len(body)).encode() if k == b"content-length" else v)
                for k, v in start["headers"]
            ]
            await send(start)
            await send({"type": "http.response.body", "body": body})

        return wrapper
