from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.middleware import require_owner
from app.services import dashboard_service

# Every route here is owner-only — it exposes revenue, customer phone numbers
# and security data.
router = APIRouter(
    prefix="/api/dashboard",
    tags=["Dashboard"],
    dependencies=[Depends(require_owner)],
)


@router.get("/stats")
async def stats(request: Request):
    """Summary cards: bookings, revenue, users, activity."""
    return await run_in_threadpool(dashboard_service.get_stats)


@router.get("/call-list")
async def call_list(request: Request):
    """Today's mobile logins, deduplicated per number — the call-back list."""
    return await run_in_threadpool(dashboard_service.get_call_list)


@router.get("/blocked")
async def blocked(
    request: Request,
    include_inactive: bool = Query(False),
):
    """Blocked IPs, with the attempt count that earned each block."""
    return await run_in_threadpool(
        dashboard_service.get_blocked_ips, include_inactive
    )


@router.get("/mail-outreach")
async def mail_outreach(request: Request):
    """Email delivery stats from email_logs."""
    return await run_in_threadpool(dashboard_service.get_mail_outreach)
