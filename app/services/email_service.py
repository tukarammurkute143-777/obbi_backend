"""
Email delivery (Resend) and the owner review queue.

send_email() never raises: it returns
  {'success': True,  'status': 'sent'}
  {'success': False, 'status': 'already_sent' | 'failed', 'message': ...}

Rules enforced here, for every caller (auto-send, approve, edit, itinerary
delivery): at most one email per recipient per calendar day (IST), counted from
`email_logs`, and attachments only from the managed itinerary directory.
"""

import asyncio
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import resend

from app.core.config import settings
from app.core.database import db
from app.services import itinerary_pdf_service

logger = logging.getLogger("email_service")

IST = timezone(timedelta(hours=5, minutes=30))
MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
_CONTROL = re.compile(r"[\r\n\t\x00-\x1f]+")


def _ist_day_start_utc() -> str:
    now = datetime.now(IST)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).isoformat()


def one_line(text: str) -> str:
    """Header-safe text: no CR/LF, so a subject can never inject headers."""
    return _CONTROL.sub(" ", text or "").strip()


# ---------------------------------------------------------------- daily limit


def _sent_today(email: str) -> bool:
    rows = (db.table("email_logs").select("id").eq("email", email)
            .in_("status", ["sent", "delivered"])
            .gte("sent_at", _ist_day_start_utc()).limit(1).execute().data)
    return bool(rows)


async def already_sent_today(email: str) -> bool:
    """True if this address was already emailed today. If the log cannot be
    read this fails closed (True): an unreadable log must not turn into a
    second email."""
    try:
        return await asyncio.to_thread(_sent_today, email.strip().lower())
    except Exception as e:
        logger.error("email_logs unreadable: %s", type(e).__name__)
        return True


def _log(email: str, email_type: str, subject: str, status: str) -> None:
    db.table("email_logs").insert({
        "email": email,
        "email_type": email_type,
        "subject": subject[:500],
        "status": status,
        "sent_at": datetime.now(timezone.utc).isoformat(),
    }).execute()


async def _log_safely(email, email_type, subject, status) -> None:
    try:
        await asyncio.to_thread(_log, email, email_type, subject, status)
    except Exception as e:
        logger.error("Writing email_logs failed: %s", type(e).__name__)


# ------------------------------------------------------------------- rendering


def render_html(body: str) -> str:
    """Plain-text body -> simple HTML. Everything is escaped: the body is
    model- or user-written and must never inject markup."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]
    inner = "".join(
        f'<p style="margin:0 0 14px;line-height:1.55">'
        f'{html.escape(p).replace(chr(10), "<br>")}</p>'
        for p in paragraphs
    )
    return (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:15px;'
        'color:#222;max-width:560px;margin:0 auto;padding:20px">'
        f'<div style="border-bottom:3px solid #e67814;margin-bottom:18px;'
        f'padding-bottom:8px;font-size:20px;font-weight:bold;color:#e67814">'
        f'Obii Cabs</div>{inner}</div>'
    )


# --------------------------------------------------------------------- sending


def _read_attachment(path: str) -> Optional[dict]:
    if not itinerary_pdf_service.is_managed_pdf(path):
        return None
    p = Path(path)
    if p.stat().st_size > MAX_ATTACHMENT_BYTES:
        return None
    return {"filename": "Obii-Cabs-Itinerary.pdf", "content": list(p.read_bytes())}


def _send_via_resend(params: dict) -> None:
    resend.api_key = settings.RESEND_API_KEY
    resend.Emails.send(params)


async def send_email(
    to_email: str,
    subject: str,
    body: str,
    email_type: str = "",
    attachment_path: Optional[str] = None,
) -> dict:
    to_email = (to_email or "").strip().lower()
    subject = one_line(subject)[:200]
    if not to_email or not subject or not body.strip():
        return {"success": False, "status": "failed",
                "message": "Email, subject aur body zaroori hain."}

    if await already_sent_today(to_email):
        return {"success": False, "status": "already_sent",
                "message": "Is customer ko aaj email jaa chuka hai."}

    if not settings.RESEND_API_KEY.strip():
        logger.error("RESEND_API_KEY is not set")
        return {"success": False, "status": "failed",
                "message": "Email service abhi available nahi hai."}

    params = {
        "from": settings.EMAIL_FROM,
        "to": [to_email],
        "subject": subject,
        "html": render_html(body),
        "text": body,
    }
    if settings.OWNER_EMAIL.strip():
        params["reply_to"] = settings.OWNER_EMAIL.strip()

    if attachment_path:
        try:
            attachment = await asyncio.to_thread(_read_attachment, attachment_path)
        except OSError:
            attachment = None
        if attachment is None:
            # Never send "see attached PDF" without the PDF.
            return {"success": False, "status": "failed",
                    "message": "Attachment available nahi hai."}
        params["attachments"] = [attachment]

    try:
        await asyncio.to_thread(_send_via_resend, params)
    except Exception as e:
        logger.error("Resend send failed: %s", type(e).__name__)
        await _log_safely(to_email, email_type, subject, "failed")
        return {"success": False, "status": "failed",
                "message": "Email bhej nahi paye. Thodi der baad try karo."}

    await _log_safely(to_email, email_type, subject, "sent")
    return {"success": True, "status": "sent"}


# ---------------------------------------------------------------- review queue


class QueueError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _enqueue(row: dict) -> dict:
    return db.table("email_review_queue").insert(row).execute().data[0]


async def enqueue_for_review(
    *, customer_email, customer_name, email_type, subject, body,
    attachment_path, overall_score, failed_checks, itinerary_id=None,
) -> dict:
    """Park an email for the owner. Raises QueueError(503) if it cannot be
    stored: the caller must then NOT send it."""
    try:
        row = await asyncio.to_thread(_enqueue, {
            "customer_email": customer_email,
            "customer_name": customer_name,
            "email_type": email_type,
            "subject": subject,
            "body": body,
            "attachment_path": attachment_path,
            "overall_score": round(float(overall_score), 2),
            "failed_checks": failed_checks,
            "itinerary_id": itinerary_id,
            "status": "pending",
        })
    except Exception as e:
        logger.error("Queueing email failed: %s", type(e).__name__)
        raise QueueError(503, "Review queue abhi available nahi hai.") from None
    return row


def _list_pending(limit: int) -> list:
    return (db.table("email_review_queue").select("*").eq("status", "pending")
            .order("created_at", desc=True).limit(limit).execute().data or [])


async def list_pending(limit: int = 100) -> list:
    try:
        return await asyncio.to_thread(_list_pending, limit)
    except Exception as e:
        logger.error("Listing queue failed: %s", type(e).__name__)
        raise QueueError(503, "Review queue abhi available nahi hai.") from None


def _claim(item_id: str) -> Optional[dict]:
    """Atomically move pending -> processing so two owners (or a double click)
    cannot send the same email twice."""
    rows = (db.table("email_review_queue").update({"status": "processing"})
            .eq("id", item_id).eq("status", "pending").execute().data)
    return rows[0] if rows else None


def _finish(item_id: str, status: str, fields: dict) -> None:
    db.table("email_review_queue").update({
        **fields,
        "status": status,
        "action_taken": status,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", item_id).execute()


def _release(item_id: str) -> None:
    db.table("email_review_queue").update({"status": "pending"}) \
        .eq("id", item_id).eq("status", "processing").execute()


async def resolve_item(item_id: str, action: str,
                       subject: Optional[str] = None,
                       body: Optional[str] = None,
                       attachment_resolver=None) -> dict:
    """
    action: 'approved' | 'edited_and_sent' | 'rejected'.
    approve/edit send the email; if sending does not succeed the item goes back
    to 'pending' so the owner can retry or reject it.
    """
    try:
        item = await asyncio.to_thread(_claim, item_id)
    except Exception as e:
        logger.error("Claiming queue item failed: %s", type(e).__name__)
        raise QueueError(503, "Review queue abhi available nahi hai.") from None
    if item is None:
        raise QueueError(409, "Yeh email pending nahi hai ya mila nahi.")

    try:
        if action == "rejected":
            await asyncio.to_thread(_finish, item_id, "rejected", {})
            return {"success": True, "status": "rejected"}

        final_subject = subject if subject is not None else item["subject"]
        final_body = body if body is not None else item["body"]

        attachment = item.get("attachment_path")
        if attachment_resolver and (attachment or item.get("itinerary_id")):
            attachment = await attachment_resolver(item)

        result = await send_email(
            item["customer_email"], final_subject, final_body,
            email_type=item.get("email_type") or "", attachment_path=attachment)
        if not result["success"]:
            await asyncio.to_thread(_release, item_id)
            status = 409 if result["status"] == "already_sent" else 502
            raise QueueError(status, result["message"])

        await asyncio.to_thread(_finish, item_id, action, {
            "subject": final_subject, "body": final_body})
        return {"success": True, "status": action, "itinerary_id": item.get("itinerary_id")}
    except QueueError:
        # Includes failures raised by the attachment resolver, which would
        # otherwise leave the item stuck in 'processing'. A no-op if the item
        # was already released or finished.
        try:
            await asyncio.to_thread(_release, item_id)
        except Exception:
            pass
        raise
    except Exception as e:
        logger.exception("Resolving queue item failed: %s", type(e).__name__)
        try:
            await asyncio.to_thread(_release, item_id)
        except Exception:
            pass
        raise QueueError(503, "Kuch galat ho gaya. Dobara try karo.") from None
