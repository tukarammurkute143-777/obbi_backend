"""
Owner-side management of AI API keys and models (see routes/dashboard.py).

All functions here are synchronous (supabase-py is) and are called through
run_in_threadpool. They return plain dicts, or raise AdminError with the HTTP
status the route should use.

Secrets: key values are encrypted before they are stored and are never
returned; listings show a masked form only.
"""

import logging
import re
from datetime import datetime, timezone

from app.core.ai_client import key_names_for
from app.core.config import settings
from app.core.crypto import decrypt_secret, encrypt_secret, mask_secret
from app.core.database import db

logger = logging.getLogger("ai_admin")

MANAGED_KEYS = ("AI_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY",
                "GEMINI_API_KEY", "ANTHROPIC_API_KEY")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")


class AdminError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _db_error(what: str, e: Exception) -> AdminError:
    logger.error("%s failed: %s", what, type(e).__name__)
    return AdminError(503, "Database abhi available nahi hai.")


def _check_id(model_id: str) -> None:
    if not _UUID.match(model_id or ""):
        raise AdminError(400, "Invalid model id.")


def _actor(user: dict) -> str:
    return str(user.get("email") or user.get("mobile") or user.get("id"))[:255]


# ------------------------------------------------------------------------ keys


def list_keys() -> dict:
    try:
        rows = db.table("api_keys_config").select(
            "key_name,key_value,updated_at,updated_by").execute().data or []
    except Exception as e:
        logger.warning("api_keys_config unreadable (%s); listing env keys only",
                       type(e).__name__)
        rows = []
    stored = {r["key_name"]: r for r in rows}

    keys = []
    for name in MANAGED_KEYS:
        row = stored.get(name)
        value = decrypt_secret(row["key_value"]) if row else None
        source = "database" if value else None
        if not value:
            value = (getattr(settings, name, "") or "").strip()
            source = "environment" if value else None
        from_db = source == "database"
        keys.append({
            "key_name": name,
            "configured": bool(value),
            "source": source,
            "masked_value": mask_secret(value) if value else None,
            "updated_at": row["updated_at"] if from_db else None,
            "updated_by": row["updated_by"] if from_db else None,
        })
    return {"keys": keys}


def update_key(key_name: str, key_value: str, user: dict) -> dict:
    if key_name not in MANAGED_KEYS:
        raise AdminError(400, "Unknown key_name.")
    value = key_value.strip()
    if len(value) < 8 or any(c.isspace() for c in value):
        raise AdminError(400, "key_value looks invalid.")
    try:
        db.table("api_keys_config").upsert({
            "key_name": key_name,
            "key_value": encrypt_secret(value),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": _actor(user),
        }, on_conflict="key_name").execute()
    except Exception as e:
        raise _db_error("update_key", e)
    logger.warning("API key %s updated by %s", key_name, _actor(user))
    return {"success": True, "key_name": key_name, "masked_value": mask_secret(value)}


# ---------------------------------------------------------------------- models


def _provider_has_key(provider: str) -> bool:
    for name in key_names_for(provider):
        if (getattr(settings, name, "") or "").strip():
            return True
        try:
            hit = db.table("api_keys_config").select("key_value") \
                .eq("key_name", name).limit(1).execute().data
        except Exception:
            continue
        if hit and decrypt_secret(hit[0]["key_value"]):
            return True
    return False


def list_models() -> dict:
    try:
        rows = (db.table("ai_models").select("*")
                .order("added_at").execute().data or [])
    except Exception as e:
        raise _db_error("list_models", e)

    # Whether a key exists for each provider, so the dashboard can warn before
    # the owner switches to a model that cannot run.
    has_key = {p: _provider_has_key(p) for p in {r["provider"] for r in rows}}
    for r in rows:
        r["key_configured"] = has_key[r["provider"]]
    return {"models": rows}


def add_model(provider: str, model_name: str, display_name: str, user: dict) -> dict:
    display_name = " ".join(display_name.split())
    if not display_name:
        raise AdminError(400, "display_name is required.")
    try:
        existing = (db.table("ai_models").select("id").eq("provider", provider)
                    .eq("model_name", model_name).limit(1).execute().data)
        if existing:
            raise AdminError(409, "Yeh model already added hai.")
        row = db.table("ai_models").insert({
            "provider": provider,
            "model_name": model_name,
            "display_name": display_name,
            "is_active": True,
            "is_default": False,
            "added_by": _actor(user),
        }).execute().data[0]
    except AdminError:
        raise
    except Exception as e:
        raise _db_error("add_model", e)
    return {"success": True, "model": row}


def activate_model(model_id: str) -> dict:
    """Make this the one default model (and mark it available)."""
    _check_id(model_id)
    try:
        target = db.table("ai_models").select("*").eq("id", model_id).execute().data
        if not target:
            raise AdminError(404, "Model nahi mila.")
        previous = (db.table("ai_models").select("id").eq("is_default", True)
                    .neq("id", model_id).execute().data or [])

        # Clear first: a partial unique index allows only one default row.
        db.table("ai_models").update({"is_default": False}) \
            .eq("is_default", True).neq("id", model_id).execute()
        try:
            db.table("ai_models").update({"is_default": True, "is_active": True}) \
                .eq("id", model_id).execute()
        except Exception:
            # Don't leave the app with no default model.
            for p in previous:
                try:
                    db.table("ai_models").update({"is_default": True}) \
                        .eq("id", p["id"]).execute()
                except Exception:
                    pass
            raise
    except AdminError:
        raise
    except Exception as e:
        raise _db_error("activate_model", e)
    return {"success": True,
            "active_model": {**target[0], "is_default": True, "is_active": True}}


def delete_model(model_id: str) -> dict:
    _check_id(model_id)
    try:
        rows = db.table("ai_models").select("id,is_default").eq("id", model_id) \
            .execute().data
        if not rows:
            raise AdminError(404, "Model nahi mila.")
        if rows[0]["is_default"]:
            raise AdminError(409, "Default model delete nahi ho sakta. "
                                  "Pehle doosra model activate karo.")
        # The is_default guard is repeated in the DELETE so a concurrent
        # activate cannot let us remove the model that just became default.
        db.table("ai_models").delete().eq("id", model_id) \
            .eq("is_default", False).execute()
    except AdminError:
        raise
    except Exception as e:
        raise _db_error("delete_model", e)
    return {"success": True}
