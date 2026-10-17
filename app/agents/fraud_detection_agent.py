"""
Fraud Detection Agent for Obii Cabs.

FraudDetectionAgent.analyze() is called at the start of every login step and
returns a FraudResult. Checks run cheapest-first and stop at the first block:

  1. IP blocklist             4. Per-IP attempt rate     7. Geo anomaly (flag)
  2. VPN / proxy / datacenter 5. Multi-account per IP
  3. Shared network (flag)    6. Device fingerprint

Failure policy: every check fails open. A Supabase, Redis or ip-api.com outage
is logged and that one check is skipped; it never blocks a user or raises.
"""

import asyncio
import ipaddress
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

from app.core.cache import cache_get, cache_set
from app.core.database import db
from app.core.middleware import invalidate_ip_cache

logger = logging.getLogger("fraud")

# Distinct accounts allowed on one IP / one device before blocking. The check
# blocks when the accounts seen *including the current one* exceed this, so a
# couple sharing a phone or WiFi is fine and a third account is not.
MAX_ACCOUNTS_PER_IP = 2
MAX_ACCOUNTS_PER_DEVICE = 2

MAX_ATTEMPTS_PER_HOUR = 10
RATE_LIMIT_BLOCK_HOURS = 24
VPN_BLOCK_HOURS = 24  # VPN exit IPs rotate between users, so don't ban forever

SHARED_NETWORK_ACCOUNTS = 5
GEO_WINDOW_MINUTES = 30

IP_REPUTATION_TTL = 3600
IP_API_URL = "http://ip-api.com/json/{ip}"  # free tier is HTTP-only
IP_API_FIELDS = "status,message,country,city,isp,proxy,hosting,mobile"
IP_API_TIMEOUT = 3.0


@dataclass
class FraudResult:
    allowed: bool = True
    status: int = 200
    reason: str = ""
    flags: dict = field(default_factory=dict)

    @property
    def message(self) -> str:
        # The specific reason stays in logs/blocked_ips; callers get this.
        return "Access blocked. Contact support." if not self.allowed else ""


# ----------------------------------------------------------------- helpers


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast)


def _subnet_prefix(ip: str) -> Optional[str]:
    """Text prefix shared by the /24 of an IPv4 address, for a LIKE query."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if addr.version != 4:
        return None
    return ".".join(ip.split(".")[:3]) + "."


async def _run(fn, *args, **kwargs):
    """supabase-py is sync; keep it off the event loop."""
    return await asyncio.to_thread(fn, *args, **kwargs)


# ------------------------------------------------------------ reputation cache


async def get_ip_reputation(ip: str) -> Optional[dict]:
    """
    {'vpn': bool, 'city': str, 'isp': str, ...} for a public IP, or None when
    the lookup is unavailable (callers must treat None as "unknown", not "bad").
    """
    cached = await cache_get(f"ip_rep:{ip}")
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=IP_API_TIMEOUT) as client:
            resp = await client.get(
                IP_API_URL.format(ip=ip), params={"fields": IP_API_FIELDS}
            )
        if resp.status_code != 200:  # incl. 429 when the 45 req/min cap is hit
            logger.warning("ip-api returned %s", resp.status_code)
            return None
        data = resp.json()
        if data.get("status") != "success":
            return None
    except Exception as e:
        logger.warning("ip-api lookup failed: %s", type(e).__name__)
        return None

    rep = {
        # `proxy` covers VPN/proxy/Tor exits, `hosting` covers datacenters.
        # Mobile carrier IPs are NATed across many users and are never flagged.
        "vpn": bool(data.get("proxy") or data.get("hosting"))
               and not data.get("mobile"),
        "proxy": bool(data.get("proxy")),
        "hosting": bool(data.get("hosting")),
        "city": data.get("city") or "",
        "country": data.get("country") or "",
        "isp": data.get("isp") or "",
    }
    await cache_set(f"ip_rep:{ip}", rep, IP_REPUTATION_TTL)
    return rep


# ------------------------------------------------------------------ blocking


def _upsert_block(row: dict) -> None:
    try:
        db.table("blocked_ips").upsert(row).execute()
    except Exception:
        # Migration not applied yet: fall back to the original columns so the
        # block is still recorded (as permanent) rather than lost.
        legacy = {k: v for k, v in row.items()
                  if k not in ("duration_hours", "expires_at")}
        db.table("blocked_ips").upsert(legacy).execute()


async def block_ip(ip: str, reason: str, duration_hours: Optional[int] = None) -> None:
    """Block an IP. duration_hours=None is a permanent block."""
    row = {
        "ip_address": ip,
        "reason": reason,
        "is_active": True,
        "duration_hours": duration_hours,
        "expires_at": (
            (_utcnow() + timedelta(hours=duration_hours)).isoformat()
            if duration_hours else None
        ),
    }
    try:
        await _run(_upsert_block, row)
    except Exception as e:
        logger.error("block_ip failed for %s: %s", ip, type(e).__name__)
        return
    # IPBlockMiddleware caches lookups; apply the block to the next request.
    invalidate_ip_cache(ip)
    logger.warning("Blocked %s (%s, %s)", ip, reason,
                   f"{duration_hours}h" if duration_hours else "permanent")


# -------------------------------------------------------------------- agent


class FraudDetectionAgent:

    @classmethod
    async def analyze(
        cls,
        ip: str,
        identifier: Optional[str] = None,
        device_fingerprint: Optional[str] = None,
    ) -> FraudResult:
        """
        identifier is the mobile or email being used to log in. Never raises;
        on internal error the request is allowed.
        """
        try:
            return await cls._analyze(ip, identifier, device_fingerprint)
        except Exception as e:
            logger.error("Fraud analysis crashed: %s", type(e).__name__)
            return FraudResult()

    @classmethod
    async def _analyze(cls, ip, identifier, device_fingerprint) -> FraudResult:
        flags: dict = {}

        # 1. Blocklist
        if await cls._is_blocked(ip):
            return cls._deny("IP blocklisted", flags)

        if _is_public_ip(ip):
            # 4. Attempt rate (before the external lookup: cheap abuse first)
            if await cls._attempts_last_hour(ip) >= MAX_ATTEMPTS_PER_HOUR:
                await block_ip(ip, "Rate limit exceeded", RATE_LIMIT_BLOCK_HOURS)
                return cls._deny("Rate limit exceeded", flags)

            # 5. VPN / proxy / datacenter
            rep = await get_ip_reputation(ip)
            if rep:
                flags["city"] = rep["city"]
                flags["isp"] = rep["isp"]

            # 6. Shared network: flag only, unless combined with a VPN
            shared = await cls._shared_network(ip, identifier)
            if shared:
                flags["shared_network"] = True
                logger.warning("Shared network %s: %s accounts in 1h", ip, shared)

            if rep and rep["vpn"]:
                flags["vpn"] = True
                reason = "VPN/Proxy detected"
                await block_ip(ip, reason, VPN_BLOCK_HOURS)
                return cls._deny(reason, flags)

        # 2. Multi-account per IP
        if identifier and await cls._accounts_exceed(
            "ip_address", ip, identifier, MAX_ACCOUNTS_PER_IP
        ):
            await block_ip(ip, "Multi-account detected")
            return cls._deny("Multi-account detected", flags)

        # 3. Device fingerprint
        if identifier and device_fingerprint and await cls._accounts_exceed(
            "device_fingerprint", device_fingerprint, identifier,
            MAX_ACCOUNTS_PER_DEVICE,
        ):
            await block_ip(ip, "Device fingerprint mismatch")
            return cls._deny("Device fingerprint mismatch", flags)

        # 7. Geo anomaly (flag only)
        if identifier and flags.get("city"):
            if await cls._geo_anomaly(identifier, flags["city"]):
                flags["geo_anomaly"] = True
                logger.warning("Geo anomaly for %s: now in %s", identifier,
                               flags["city"])

        return FraudResult(True, 200, "", flags)

    @staticmethod
    def _deny(reason: str, flags: dict) -> FraudResult:
        return FraudResult(False, 403, reason, {**flags, "blocked_reason": reason})

    # ---- individual checks. Each returns the "safe" value on error. ----

    @staticmethod
    async def _is_blocked(ip: str) -> bool:
        def query():
            return (db.table("blocked_ips").select("*")
                    .eq("ip_address", ip).eq("is_active", True).execute())
        try:
            rows = (await _run(query)).data or []
        except Exception as e:
            logger.error("Blocklist check failed: %s", type(e).__name__)
            return False

        now = _utcnow()
        for row in rows:
            expires = _parse_ts(row.get("expires_at"))
            if expires is None or expires > now:
                return True
            # Expired: deactivate so the middleware stops matching it too.
            try:
                await _run(lambda r=row: db.table("blocked_ips")
                           .update({"is_active": False}).eq("id", r["id"]).execute())
                invalidate_ip_cache(ip)
            except Exception:
                pass
        return False

    @staticmethod
    async def _attempts_last_hour(ip: str) -> int:
        since = (_utcnow() - timedelta(hours=1)).isoformat()

        def query():
            return (db.table("login_attempts").select("id", count="exact")
                    .eq("ip_address", ip).gte("created_at", since).execute())
        try:
            res = await _run(query)
            return res.count if res.count is not None else len(res.data or [])
        except Exception as e:
            logger.error("Rate check failed: %s", type(e).__name__)
            return 0

    @staticmethod
    async def _shared_network(ip: str, identifier: Optional[str]) -> int:
        """Distinct accounts in the last hour across this IP's /24, if >= limit."""
        prefix = _subnet_prefix(ip)
        if not prefix:
            return 0
        since = (_utcnow() - timedelta(hours=1)).isoformat()

        def query():
            return (db.table("login_attempts").select("mobile,email")
                    .like("ip_address", prefix + "%").gte("created_at", since)
                    .execute())
        try:
            rows = (await _run(query)).data or []
        except Exception as e:
            logger.error("Shared network check failed: %s", type(e).__name__)
            return 0
        accounts = {r.get("mobile") or r.get("email") for r in rows} - {None}
        if identifier:
            accounts.add(identifier)
        return len(accounts) if len(accounts) >= SHARED_NETWORK_ACCOUNTS else 0

    @staticmethod
    async def _accounts_exceed(column: str, value: str, identifier: str,
                               limit: int) -> bool:
        def query():
            return (db.table("login_attempts").select("mobile,email")
                    .eq(column, value).eq("success", True).execute())
        try:
            rows = (await _run(query)).data or []
        except Exception as e:
            logger.error("Account check (%s) failed: %s", column, type(e).__name__)
            return False
        accounts = {r.get("mobile") or r.get("email") for r in rows} - {None}
        accounts.add(identifier)
        return len(accounts) > limit

    @staticmethod
    async def _geo_anomaly(identifier: str, city: str) -> bool:
        since = (_utcnow() - timedelta(minutes=GEO_WINDOW_MINUTES)).isoformat()
        column = "email" if "@" in identifier else "mobile"

        def query():
            return (db.table("login_attempts").select("fraud_flags")
                    .eq(column, identifier).gte("created_at", since).execute())
        try:
            rows = (await _run(query)).data or []
        except Exception as e:
            logger.error("Geo check failed: %s", type(e).__name__)
            return False
        for row in rows:
            prev = (row.get("fraud_flags") or {}).get("city")
            if prev and prev.lower() != city.lower():
                return True
        return False
