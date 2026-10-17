import html

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.core.ai_client import invalidate_active_model, invalidate_keys
from app.core.middleware import require_owner
from app.models.ai_admin import AddModelRequest, UpdateKeyRequest
from app.models.email import EditQueuedEmailRequest
from app.services import (
    ai_admin_service,
    dashboard_service,
    email_service,
    itinerary_pdf_service,
    itinerary_service,
)
from app.services.ai_admin_service import AdminError

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


# ------------------------------------------------- AI keys & models (owner only)


async def _admin(fn, *args):
    try:
        return await run_in_threadpool(fn, *args)
    except AdminError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@router.get("/api-keys")
async def list_api_keys(request: Request):
    """AI provider keys, masked. The full value is never returned."""
    return await _admin(ai_admin_service.list_keys)


@router.put("/api-keys")
async def update_api_key(
    request: Request,
    body: UpdateKeyRequest,
    owner: dict = Depends(require_owner),
):
    """Save a key (encrypted) and apply it to the next AI request."""
    result = await _admin(
        ai_admin_service.update_key, body.key_name, body.key_value, owner)
    invalidate_keys()
    return result


@router.get("/ai-models")
async def list_ai_models(request: Request):
    return await _admin(ai_admin_service.list_models)


@router.post("/ai-models", status_code=201)
async def add_ai_model(
    request: Request,
    body: AddModelRequest,
    owner: dict = Depends(require_owner),
):
    return await _admin(
        ai_admin_service.add_model,
        body.provider, body.model_name, body.display_name, owner)


@router.put("/ai-models/{model_id}/activate")
async def activate_ai_model(request: Request, model_id: str):
    """Make this the default model; the next AI request uses it."""
    result = await _admin(ai_admin_service.activate_model, model_id)
    await invalidate_active_model()
    return result


@router.delete("/ai-models/{model_id}")
async def delete_ai_model(request: Request, model_id: str):
    """Delete a model. The current default cannot be deleted."""
    result = await _admin(ai_admin_service.delete_model, model_id)
    await invalidate_active_model()
    return result


# ------------------------------------------------ Email review queue (owner only)


async def _queue_attachment(item: dict):
    """Path of the PDF to send with a queued email, re-creating it from the
    saved itinerary if the cached file is gone. Refuses (409) rather than let
    an email that says 'PDF attached' go out without one."""
    if itinerary_pdf_service.is_managed_pdf(item.get("attachment_path")):
        return item["attachment_path"]
    if item.get("itinerary_id"):
        row = await itinerary_service.get_itinerary(item["itinerary_id"])
        if row:
            return await itinerary_service.ensure_pdf(row)
    raise email_service.QueueError(
        409, "Attachment dobara nahi ban paya. Is email ko reject karke naya banao.")


async def _resolve(item_id: str, action: str, subject=None, body=None):
    if not itinerary_service.is_valid_id(item_id):
        raise HTTPException(status_code=404, detail="Email nahi mila.")
    try:
        result = await email_service.resolve_item(
            item_id, action, subject, body, attachment_resolver=_queue_attachment)
    except email_service.QueueError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    except LookupError:
        raise HTTPException(status_code=503, detail="Database abhi available nahi hai.")
    if result.get("itinerary_id") and action != "rejected":
        await itinerary_service.update_itinerary(result["itinerary_id"], emailed=True)
    return {k: v for k, v in result.items() if k != "itinerary_id"}


@router.get("/email-queue")
async def email_queue(request: Request):
    """Emails the reviewer held back, newest first."""
    try:
        items = await email_service.list_pending()
    except email_service.QueueError as e:
        raise HTTPException(status_code=e.status, detail=e.message)
    return {"total": len(items), "emails": items}


@router.put("/email-queue/{item_id}/approve")
async def approve_queued_email(request: Request, item_id: str):
    """Send the email as written."""
    return await _resolve(item_id, "approved")


@router.put("/email-queue/{item_id}/reject")
async def reject_queued_email(request: Request, item_id: str):
    """Discard the email without sending."""
    return await _resolve(item_id, "rejected")


@router.put("/email-queue/{item_id}/edit")
async def edit_queued_email(request: Request, item_id: str, body: EditQueuedEmailRequest):
    """Send the email with the owner's corrected subject and body."""
    # The guardrails middleware HTML-encodes request text; the email renderer
    # escapes on its own, so undo that here or apostrophes show as &#x27;.
    return await _resolve(item_id, "edited_and_sent",
                          email_service.one_line(html.unescape(body.subject)),
                          html.unescape(body.body))
