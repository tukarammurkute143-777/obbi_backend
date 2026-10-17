import html
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from starlette.concurrency import run_in_threadpool

from app.agents.supervisor import supervisor
from app.core.ai_client import invalidate_active_model, invalidate_keys
from app.core.config import settings
from app.core.middleware import require_owner
from app.core.rate_limit import limiter
from app.models.ai_admin import AddModelRequest, UpdateKeyRequest
from app.models.blog import UpdateBlogRequest
from app.models.email import EditQueuedEmailRequest
from app.services import (
    ai_admin_service,
    blog_service,
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


# ------------------------------------------------------ Blogs (owner only)
# Publishing happens ONLY through PUT /blogs/{id}/publish. Generating a blog
# always saves a draft.


async def _blog(fn, *args):
    try:
        return await fn(*args)
    except blog_service.BlogError as e:
        raise HTTPException(status_code=e.status, detail=e.message)


@router.post("/blogs/generate", status_code=201)
@limiter.limit(settings.RATE_LIMIT_AI)
async def generate_blog(request: Request, body: dict = Body(...)):
    """Write a blog with the AI and save it as a draft for review."""
    result = await supervisor.blog(body)
    if not result["success"]:
        status = result.get("status", 503)
        if status == 400:
            raise HTTPException(
                status_code=400,
                detail={"field": result.get("field"), "message": result["message"]})
        raise HTTPException(status_code=status, detail=result["message"])
    return result


@router.get("/blogs")
async def list_blogs(
    request: Request,
    status: Optional[str] = Query(None, description="draft | published | rejected"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
):
    """Blogs without their body, plus per-status counts (counts.draft = waiting
    for your review)."""
    return await _blog(blog_service.list_blogs, status, limit, offset)


@router.get("/blogs/{blog_id}")
async def get_blog(request: Request, blog_id: str):
    return await _blog(blog_service.get_blog, blog_id)


@router.put("/blogs/{blog_id}/publish")
async def publish_blog(request: Request, blog_id: str):
    """Make a blog public. The only way to publish."""
    row = await _blog(blog_service.publish_blog, blog_id)
    return {"success": True, "id": row["id"], "slug": row["slug"],
            "status": row["status"], "published_at": row["published_at"]}


@router.put("/blogs/{blog_id}/reject")
async def reject_blog(request: Request, blog_id: str):
    """Reject a draft, or take a published blog down."""
    row = await _blog(blog_service.reject_blog, blog_id)
    return {"success": True, "id": row["id"], "status": row["status"]}


@router.put("/blogs/{blog_id}")
async def edit_blog(request: Request, blog_id: str, body: UpdateBlogRequest):
    """Edit title and/or content. Does not change the blog status."""
    # The guardrails middleware HTML-encodes the title; undo it for storage.
    title = html.unescape(body.title) if body.title is not None else None
    row = await _blog(blog_service.update_blog, blog_id, title, body.content)
    return {"success": True, "blog": row}


@router.delete("/blogs/{blog_id}")
async def delete_blog(request: Request, blog_id: str):
    """Delete a draft or rejected blog. Published blogs cannot be deleted."""
    await _blog(blog_service.delete_blog, blog_id)
    return {"success": True}
