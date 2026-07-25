import random
from datetime import date, datetime

from app.core.database import db

# Columns the client may never set directly — they are derived or generated.
DERIVED_FIELDS = {"booking_number", "total_days", "remaining_amount", "partner_payout"}


def generate_booking_number() -> str:
    """OB-YYYYMMDD-1234, retried on the off-chance of a same-day collision."""
    today = datetime.utcnow().strftime("%Y%m%d")
    for _ in range(6):
        candidate = f"OB-{today}-{random.randint(1000, 9999)}"
        existing = (
            db.table("bookings")
            .select("id")
            .eq("booking_number", candidate)
            .limit(1)
            .execute()
        )
        if not existing.data:
            return candidate
    # Fall back to a microsecond stamp rather than fail the booking.
    return f"OB-{today}-{datetime.utcnow().strftime('%H%M%S%f')}"


def _to_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def compute_derived(data: dict) -> dict:
    """
    Fill total_days / remaining_amount / partner_payout from the other fields.
    `data` must already hold the merged final values (existing row + changes).
    """
    pickup = _to_date(data.get("pickup_date"))
    drop = _to_date(data.get("drop_date"))
    if pickup and drop:
        # Inclusive: a same-day trip is 1 day.
        data["total_days"] = (drop - pickup).days + 1
    elif pickup:
        data["total_days"] = 1

    total_rate = float(data.get("total_rate") or 0)
    advance = float(data.get("advance_paid") or 0)
    extra = float(data.get("extra_charges") or 0)
    data["remaining_amount"] = round(total_rate + extra - advance, 2)

    if data.get("is_partner_vehicle"):
        commission = float(data.get("partner_commission") or 0)
        data["partner_payout"] = round(total_rate + extra - commission, 2)
    else:
        data["partner_commission"] = 0
        data["partner_payout"] = 0

    # Keep payment_status consistent with the money actually collected.
    billable = round(total_rate + extra, 2)
    if advance <= 0:
        data.setdefault("payment_status", "pending")
    elif advance >= billable:
        data["payment_status"] = "paid"
    else:
        data["payment_status"] = "partial"

    return data


def create_booking(payload: dict, created_by: dict) -> dict:
    data = {k: v for k, v in payload.items() if k not in DERIVED_FIELDS}
    data["booking_number"] = generate_booking_number()
    data.setdefault("status", "pending")
    data = compute_derived(data)

    result = db.table("bookings").insert(data).execute()
    if not result.data:
        raise ValueError("Booking create nahi hui. Dobara try karo.")
    return result.data[0]


def list_bookings(
    status: str | None = None,
    payment_status: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    query = db.table("bookings").select("*", count="exact")

    if status:
        query = query.eq("status", status)
    if payment_status:
        query = query.eq("payment_status", payment_status)
    if search:
        safe = search.replace(",", " ").replace("*", "")
        query = query.or_(
            f"customer_name.ilike.%{safe}%,"
            f"customer_mobile.ilike.%{safe}%,"
            f"booking_number.ilike.%{safe}%"
        )

    result = (
        query.order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )

    return {
        "total": result.count if result.count is not None else len(result.data or []),
        "limit": limit,
        "offset": offset,
        "bookings": result.data or [],
    }


def list_bookings_for_mobile(mobile: str, limit: int = 50, offset: int = 0) -> dict:
    result = (
        db.table("bookings")
        .select("*", count="exact")
        .eq("customer_mobile", mobile)
        .order("created_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return {
        "total": result.count if result.count is not None else len(result.data or []),
        "limit": limit,
        "offset": offset,
        "bookings": result.data or [],
    }


def get_booking(booking_id: str) -> dict | None:
    result = (
        db.table("bookings")
        .select("*")
        .eq("id", booking_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_booking(booking_id: str, changes: dict) -> dict | None:
    existing = get_booking(booking_id)
    if not existing:
        return None

    changes = {k: v for k, v in changes.items() if k not in DERIVED_FIELDS}

    # An explicit payment_status is a deliberate override (e.g. marking a
    # refund) and must survive the derivation below.
    explicit_payment_status = changes.get("payment_status")

    # Derived values depend on fields the caller may not have sent, so compute
    # against the merged row and then write back only what actually changes.
    merged = compute_derived({**existing, **changes})
    for field in ("total_days", "remaining_amount", "partner_payout",
                  "partner_commission", "payment_status"):
        changes[field] = merged[field]

    if explicit_payment_status is not None:
        changes["payment_status"] = explicit_payment_status

    result = (
        db.table("bookings").update(changes).eq("id", booking_id).execute()
    )
    return result.data[0] if result.data else None
