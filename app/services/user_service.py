from app.core.database import db


def serialize_user(user: dict, is_owner: bool = False) -> dict:
    """Shape a `users` row for API output, with the id coerced to str."""
    return {
        "id": str(user.get("id")),
        "name": user.get("name"),
        "email": user.get("email"),
        "mobile": user.get("mobile"),
        "login_type": user.get("login_type"),
        "location": user.get("location"),
        "is_new_user": user.get("is_new_user"),
        "total_visits": user.get("total_visits") or 0,
        "last_login": user.get("last_login"),
        "created_at": user.get("created_at"),
        "is_owner": is_owner,
    }


def email_taken_by_other(email: str, user_id: str) -> bool:
    result = (
        db.table("users")
        .select("id")
        .eq("email", email)
        .neq("id", user_id)
        .limit(1)
        .execute()
    )
    return bool(result.data)


def update_profile(user_id: str, changes: dict) -> dict:
    result = (
        db.table("users").update(changes).eq("id", user_id).execute()
    )
    if not result.data:
        raise ValueError("Profile update nahi hua. User mila hi nahi.")
    return result.data[0]


def get_visit_history(user: dict, limit: int = 50) -> dict:
    """
    Login history for this user.

    Reads `login_attempts` rather than `user_sessions`: the auth flow writes an
    attempt row on every send-otp/verify-otp, while nothing currently populates
    user_sessions, so that table would always come back empty.
    """
    query = db.table("login_attempts").select(
        "ip_address, login_type, device_fingerprint, success, created_at"
    )

    mobile = user.get("mobile")
    email = user.get("email")
    if mobile and email:
        query = query.or_(f"mobile.eq.{mobile},email.eq.{email}")
    elif mobile:
        query = query.eq("mobile", mobile)
    elif email:
        query = query.eq("email", email)
    else:
        return {"total_visits": user.get("total_visits") or 0,
                "successful_logins": 0, "visits": []}

    result = (
        query.eq("success", True)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    rows = result.data or []

    return {
        "total_visits": user.get("total_visits") or 0,
        "successful_logins": len(rows),
        "visits": [
            {
                "ip_address": r.get("ip_address"),
                "login_type": r.get("login_type"),
                "device_fingerprint": r.get("device_fingerprint"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ],
    }
