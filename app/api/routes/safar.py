import html
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from app.agents.avatar_agent import SessionAccessError
from app.agents.supervisor import supervisor
from app.core.config import settings
from app.core.middleware import get_current_user, is_owner
from app.core.rate_limit import limiter
from app.models.chat import ChatRequest
from app.models.email import SendItineraryEmailRequest
from app.services import chat_session_service, email_service, itinerary_service

logger = logging.getLogger("safar")

router = APIRouter(prefix="/api/safar", tags=["Safar"])


@router.get("/route")
@limiter.limit(settings.RATE_LIMIT_SAFAR)
@limiter.limit(settings.RATE_LIMIT_USER_HOUR)
async def get_route(
    request: Request,
    origin: str = Query(..., alias="from", min_length=2, max_length=200),
    destination: str = Query(..., alias="to", min_length=2, max_length=200),
    detail: Literal["basic", "full", "multi"] = Query(
        "basic",
        description="basic: distance & time, full: + turn-by-turn waypoints, "
                    "multi: up to 3 route options",
    ),
):
    result = await supervisor.route(origin, destination, detail)
    if not result["success"]:
        raise HTTPException(
            status_code=result.get("status", 500), detail=result["message"]
        )
    return {**result, "from": origin.strip(), "to": destination.strip()}


@router.get("/hotels")
@limiter.limit(settings.RATE_LIMIT_SAFAR)
@limiter.limit(settings.RATE_LIMIT_USER_HOUR)
async def get_hotels(
    request: Request,
    destination: str = Query(..., min_length=2, max_length=100),
    type: Literal["all", "budget", "premium"] = Query(
        "all", description="all: near popular attractions, budget, or premium (luxury)"
    ),
    check_in: Optional[str] = Query(None, description="YYYY-MM-DD"),
    check_out: Optional[str] = Query(None, description="YYYY-MM-DD"),
    guests: int = Query(1, ge=1, le=20),
):
    result = await supervisor.hotel(destination, type, check_in, check_out, guests)
    if not result["success"]:
        raise HTTPException(
            status_code=result.get("status", 500), detail=result["message"]
        )
    return result


@router.post("/itinerary")
@limiter.limit(settings.RATE_LIMIT_AI)
async def create_itinerary(
    request: Request,
    body: dict = Body(
        ...,
        examples=[{
            "from": "Pune", "to": "Shirdi", "days": 2, "people": 4,
            "budget": "mid", "trip_type": "pilgrimage",
            "special_requests": "vegetarian food only",
        }],
    ),
):
    """
    AI-generated day-by-day itinerary. budget: budget | mid | premium.
    trip_type: pilgrimage | family | adventure | business | leisure.
    400 names the invalid field; 503 means generation failed, try again.
    """
    result = await supervisor.itinerary(body)
    if not result["success"]:
        status = result.get("status", 503)
        if status == 400:
            raise HTTPException(
                status_code=400,
                detail={"field": result.get("field"), "message": result["message"]},
            )
        raise HTTPException(status_code=status, detail=result["message"])

    # Saved per user, even when the plan itself came from the shared cache.
    # If saving fails the customer still gets their plan, just without an id
    # (so no PDF download) rather than losing a generation we already paid for.
    itinerary_id = await itinerary_service.save_itinerary(
        request.state.user_id, result["trip"], result["itinerary"])
    return {**result, "itinerary_id": itinerary_id}


async def _load_own_itinerary(itinerary_id: str, user: dict) -> dict:
    """The itinerary row if it belongs to the caller (or the caller is the
    owner). Someone else's id looks exactly like a missing one."""
    if not itinerary_service.is_valid_id(itinerary_id):
        raise HTTPException(status_code=404, detail="Itinerary nahi mili.")
    try:
        row = await itinerary_service.get_itinerary(itinerary_id)
    except LookupError:
        raise HTTPException(status_code=503, detail="Database abhi available nahi hai.")
    if not row or (str(row.get("user_id")) != str(user["id"]) and not is_owner(user)):
        raise HTTPException(status_code=404, detail="Itinerary nahi mili.")
    return row


async def _pdf_for(row: dict) -> str:
    try:
        return await itinerary_service.ensure_pdf(row)
    except Exception as e:
        logger.error("PDF generation failed: %s", type(e).__name__)
        raise HTTPException(status_code=503, detail="PDF abhi nahi ban payi. Try again.")


@router.get("/itinerary/{itinerary_id}/download")
@limiter.limit(settings.RATE_LIMIT_USER_HOUR)
async def download_itinerary(
    request: Request,
    itinerary_id: str,
    user: dict = Depends(get_current_user),
):
    row = await _load_own_itinerary(itinerary_id, user)
    path = await _pdf_for(row)
    await itinerary_service.update_itinerary(itinerary_id, downloaded=True)
    name = "".join(c for c in str(row.get("to_city") or "trip") if c.isalnum())
    return FileResponse(
        path, media_type="application/pdf",
        filename=f"Obii-Cabs-{name or 'trip'}-Itinerary.pdf")


@router.post("/itinerary/{itinerary_id}/send-email")
@limiter.limit(settings.RATE_LIMIT_EMAIL)
async def email_itinerary(
    request: Request,
    itinerary_id: str,
    body: SendItineraryEmailRequest,
    user: dict = Depends(get_current_user),
):
    """Email the itinerary PDF. At most one email per address per day."""
    row = await _load_own_itinerary(itinerary_id, user)
    path = await _pdf_for(row)

    plan = row.get("itinerary_data") or {}
    name = (user.get("name") or "Dost").split()[0]
    summary = (plan.get("summary") or "").strip()
    text = (
        f"Namaste {name}!\n\n"
        f"Aapki {row.get('from_city')} se {row.get('to_city')} ki "
        f"{row.get('days')}-din ki itinerary ready hai. PDF is email ke saath "
        "attach hai - isme din-ba-din plan, jagahein, hotel aur travel tips sab hain.\n\n"
        + (f"{summary}\n\n" if summary else "")
        + "Trip book karna ho ya plan mein kuch badalna ho, bas humein call karein. "
        "Rates ke liye bhi Obii Cabs se seedhe baat karein.\n\n"
        f"Call karein: {settings.OWNER_PHONE}"
    )

    result = await email_service.send_email(
        body.email, f"Aapki {row.get('to_city')} itinerary ready hai! 📋", text,
        email_type="itinerary", attachment_path=path)

    if result["status"] == "already_sent":
        raise HTTPException(status_code=409, detail="already_sent")
    if not result["success"]:
        raise HTTPException(status_code=502, detail=result["message"])
    await itinerary_service.update_itinerary(itinerary_id, emailed=True)
    return {"success": True, "message": "Itinerary email bhej di gayi hai."}


# ------------------------------------------------------------------ Safar chat


@router.post("/chat")
@limiter.limit(settings.RATE_LIMIT_CHAT)
async def chat(
    request: Request,
    body: ChatRequest,
    user: dict = Depends(get_current_user),
):
    """One message to Safar. Pass the returned session_id back to continue."""
    # The guardrails middleware HTML-encodes request text; undo it so
    # "what's the distance" is read as typed.
    try:
        return await supervisor.chat(
            html.unescape(body.message), user, body.session_id, body.language)
    except SessionAccessError:
        raise HTTPException(status_code=403, detail="Yeh session aapka nahi hai.")


async def _own_session(session_id: str, user: dict) -> dict:
    if not chat_session_service.is_valid_id(session_id):
        raise HTTPException(status_code=404, detail="Session nahi mili.")
    session = await chat_session_service.load(session_id)
    # Someone else's session looks exactly like a missing one.
    if not session or str(session.get("user_id")) != str(user["id"]):
        raise HTTPException(status_code=404, detail="Session nahi mili.")
    return session


@router.get("/session/{session_id}")
async def get_session(
    request: Request,
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Conversation history (last 10 messages) and state of one session."""
    s = await _own_session(session_id, user)
    return {
        "session_id": s["session_id"],
        "language": s["language"],
        "booking_confirmed": s["booking_confirmed"],
        "messages": s["messages"],
        "context": {k: v for k, v in (s.get("context") or {}).items()
                    if k not in ("awaiting", "pending_intent")},
        "last_intent": s.get("last_intent"),
    }


@router.delete("/session/{session_id}")
async def delete_session(
    request: Request,
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """Clear a conversation: its history is deleted."""
    s = await _own_session(session_id, user)
    await chat_session_service.clear(s)
    return {"success": True}
