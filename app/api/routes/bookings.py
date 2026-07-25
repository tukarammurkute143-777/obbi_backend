from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from starlette.concurrency import run_in_threadpool

from app.core.middleware import get_current_user, is_owner, require_owner
from app.models.booking import BookingCreate, BookingUpdate
from app.services import booking_service

router = APIRouter(prefix="/api/bookings", tags=["Bookings"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_booking(
    request: Request,
    body: BookingCreate,
    user: dict = Depends(get_current_user),
):
    """
    Create a booking. Any authenticated user may book; a non-owner can only
    book under their own registered mobile number.
    """
    payload = body.model_dump(mode="json", exclude_none=True)

    if not is_owner(user):
        user_mobile = (user.get("mobile") or "").strip()
        if user_mobile and payload["customer_mobile"] != user_mobile:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Apne registered mobile se hi booking kar sakte ho.",
            )

    try:
        booking = await run_in_threadpool(
            booking_service.create_booking, payload, user
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"success": True, "message": "Booking ho gayi! 🚗", "booking": booking}


@router.get("")
async def list_bookings(
    request: Request,
    status_filter: str | None = Query(None, alias="status"),
    payment_status: str | None = Query(None),
    search: str | None = Query(None, min_length=2, max_length=60),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    """
    Owner sees every booking, with filters and search. A regular user gets only
    the bookings made against their own mobile number.
    """
    if is_owner(user):
        return await run_in_threadpool(
            booking_service.list_bookings,
            status_filter,
            payment_status,
            search,
            limit,
            offset,
        )

    mobile = (user.get("mobile") or "").strip()
    if not mobile:
        return {"total": 0, "limit": limit, "offset": offset, "bookings": []}

    return await run_in_threadpool(
        booking_service.list_bookings_for_mobile, mobile, limit, offset
    )


@router.get("/{booking_id}")
async def get_booking(
    request: Request,
    booking_id: str,
    user: dict = Depends(get_current_user),
):
    """Single booking. Owner sees any; a user sees only their own."""
    booking = await run_in_threadpool(booking_service.get_booking, booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking nahi mili.")

    if not is_owner(user):
        user_mobile = (user.get("mobile") or "").strip()
        if not user_mobile or booking.get("customer_mobile") != user_mobile:
            # 404 rather than 403 so booking ids can't be probed for existence.
            raise HTTPException(status_code=404, detail="Booking nahi mili.")

    return {"booking": booking}


@router.put("/{booking_id}")
async def update_booking(
    request: Request,
    booking_id: str,
    body: BookingUpdate,
    owner: dict = Depends(require_owner),
):
    """
    Update a booking — owner only, since this covers rates, driver assignment,
    payment status and cancellation.
    """
    changes = body.model_dump(mode="json", exclude_none=True)

    booking = await run_in_threadpool(
        booking_service.update_booking, booking_id, changes
    )
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking nahi mili.")

    return {"success": True, "message": "Booking update ho gayi.", "booking": booking}
