"""
Dashboard aggregates.

Supabase's Python client has no SUM/GROUP BY builder, so money totals are
summed in Python over the fetched columns. That is fine at this scale (a single
cab business); if bookings grow past a few thousand rows, move these to
Postgres views or RPCs and select from those instead.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.core.database import db

# The business runs on IST, so "today" must mean today in India, not UTC.
IST = ZoneInfo("Asia/Kolkata")


def _day_bounds_utc(days_ago: int = 0) -> tuple[str, str]:
    """UTC ISO bounds for an IST calendar day, for timestamptz comparisons."""
    now_ist = datetime.now(IST)
    target = (now_ist - timedelta(days=days_ago)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_utc = target.astimezone(ZoneInfo("UTC"))
    end_utc = (target + timedelta(days=1)).astimezone(ZoneInfo("UTC"))
    return start_utc.isoformat(), end_utc.isoformat()


def _count(table: str, **filters) -> int:
    query = db.table(table).select("id", count="exact")
    for column, value in filters.items():
        query = query.eq(column, value)
    result = query.limit(1).execute()
    return result.count or 0


def _sum(rows: list[dict], column: str) -> float:
    return round(sum(float(r.get(column) or 0) for r in rows), 2)


def get_stats() -> dict:
    today_start, today_end = _day_bounds_utc()

    bookings = (
        db.table("bookings")
        .select(
            "id, status, payment_status, total_rate, advance_paid, "
            "extra_charges, remaining_amount, partner_commission, created_at"
        )
        .execute()
    ).data or []

    expenses = (
        db.table("expenses").select("total_expense").execute()
    ).data or []

    todays_bookings = [
        b for b in bookings if (b.get("created_at") or "") >= today_start
    ]
    by_status: dict[str, int] = {}
    for b in bookings:
        key = b.get("status") or "unknown"
        by_status[key] = by_status.get(key, 0) + 1

    gross_revenue = _sum(bookings, "total_rate") + _sum(bookings, "extra_charges")
    collected = _sum(bookings, "advance_paid")
    total_expense = _sum(expenses, "total_expense")

    new_users_today = (
        db.table("users")
        .select("id", count="exact")
        .gte("created_at", today_start)
        .lt("created_at", today_end)
        .limit(1)
        .execute()
    ).count or 0

    logins_today = (
        db.table("login_attempts")
        .select("id", count="exact")
        .eq("success", True)
        .gte("created_at", today_start)
        .lt("created_at", today_end)
        .limit(1)
        .execute()
    ).count or 0

    return {
        "bookings": {
            "total": len(bookings),
            "today": len(todays_bookings),
            "by_status": by_status,
            "pending_payment": sum(
                1 for b in bookings if b.get("payment_status") in ("pending", "partial")
            ),
        },
        "revenue": {
            "gross": gross_revenue,
            "collected": collected,
            "outstanding": _sum(bookings, "remaining_amount"),
            "partner_commission": _sum(bookings, "partner_commission"),
            "expenses": total_expense,
            "net_profit": round(collected - total_expense, 2),
        },
        "users": {
            "total": _count("users"),
            "new_today": new_users_today,
        },
        "activity": {
            "successful_logins_today": logins_today,
            "blocked_ips": _count("blocked_ips", is_active=True),
            "reviews": _count("reviews"),
        },
        "generated_at": datetime.now(IST).isoformat(),
    }


def get_call_list() -> dict:
    """
    Today's mobile logins — the owner's call-back list.

    One entry per phone number (most recent login first), enriched with the
    matching users row so the owner can see whether they are a new lead.
    """
    today_start, today_end = _day_bounds_utc()

    attempts = (
        db.table("login_attempts")
        .select("ip_address, mobile, login_type, success, created_at")
        .eq("login_type", "mobile")
        .eq("success", True)
        .gte("created_at", today_start)
        .lt("created_at", today_end)
        .order("created_at", desc=True)
        .execute()
    ).data or []

    # Collapse repeat logins from the same number.
    unique: dict[str, dict] = {}
    for a in attempts:
        mobile = a.get("mobile")
        if mobile and mobile not in unique:
            unique[mobile] = a

    users_by_mobile: dict[str, dict] = {}
    if unique:
        rows = (
            db.table("users")
            .select("id, name, email, mobile, location, total_visits, is_new_user")
            .in_("mobile", list(unique.keys()))
            .execute()
        ).data or []
        users_by_mobile = {r["mobile"]: r for r in rows if r.get("mobile")}

    call_list = []
    for mobile, attempt in unique.items():
        user = users_by_mobile.get(mobile, {})
        call_list.append(
            {
                "mobile": mobile,
                "name": user.get("name"),
                "email": user.get("email"),
                "location": user.get("location"),
                "total_visits": user.get("total_visits") or 1,
                "is_new_user": user.get("is_new_user", True),
                "user_id": str(user["id"]) if user.get("id") else None,
                "ip_address": attempt.get("ip_address"),
                "logged_in_at": attempt.get("created_at"),
            }
        )

    return {
        "date": datetime.now(IST).date().isoformat(),
        "total_logins": len(attempts),
        "unique_callers": len(call_list),
        "call_list": call_list,
    }


def get_blocked_ips(include_inactive: bool = False) -> dict:
    query = db.table("blocked_ips").select("*")
    if not include_inactive:
        query = query.eq("is_active", True)

    rows = (query.order("blocked_at", desc=True).execute()).data or []

    # How many login attempts each blocked IP made, for context on the block.
    for row in rows:
        attempts = (
            db.table("login_attempts")
            .select("id", count="exact")
            .eq("ip_address", row.get("ip_address"))
            .limit(1)
            .execute()
        )
        row["login_attempts"] = attempts.count or 0

    return {
        "total": len(rows),
        "active_only": not include_inactive,
        "blocked_ips": rows,
    }


def get_mail_outreach() -> dict:
    today_start, _ = _day_bounds_utc()
    week_start, _ = _day_bounds_utc(days_ago=6)

    logs = (
        db.table("email_logs")
        .select("id, email, email_type, subject, status, sent_at")
        .order("sent_at", desc=True)
        .execute()
    ).data or []

    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for log in logs:
        t = log.get("email_type") or "unknown"
        s = log.get("status") or "unknown"
        by_type[t] = by_type.get(t, 0) + 1
        by_status[s] = by_status.get(s, 0) + 1

    sent_today = sum(1 for l in logs if (l.get("sent_at") or "") >= today_start)
    sent_this_week = sum(1 for l in logs if (l.get("sent_at") or "") >= week_start)

    delivered = by_status.get("sent", 0) + by_status.get("delivered", 0)
    total = len(logs)
    unique_recipients = len({l.get("email") for l in logs if l.get("email")})

    return {
        "total_sent": total,
        "sent_today": sent_today,
        "sent_this_week": sent_this_week,
        "unique_recipients": unique_recipients,
        "delivered": delivered,
        "failed": by_status.get("failed", 0),
        "delivery_rate": round(delivered / total * 100, 1) if total else 0.0,
        "by_type": by_type,
        "by_status": by_status,
        "recent": logs[:20],
    }
