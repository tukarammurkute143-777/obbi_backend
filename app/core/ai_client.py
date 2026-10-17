"""
Provider-agnostic AI client.

    from app.core.ai_client import ai_client
    text = await ai_client.generate(prompt, system_prompt)

The provider, model and API key are resolved on every call:

  model: Supabase `ai_models` row with is_default (cached in Redis for 5 min,
         dropped by invalidate_active_model() when the owner switches model),
         falling back to AI_PROVIDER / AI_MODEL from the environment.
  key:   Supabase `api_keys_config` (encrypted), then the environment.

Providers are plain HTTPS calls (no vendor SDKs) behind one interface, picked
by get_provider(). Failures raise AIClientError; `fatal` marks errors a retry
cannot fix (bad key, unknown provider, no key configured).
"""

import asyncio
import logging
import time
from typing import Optional

import httpx

from app.core.cache import cache_delete, cache_get, cache_set
from app.core.config import settings
from app.core.crypto import decrypt_secret
from app.core.database import db

logger = logging.getLogger("ai_client")

ACTIVE_MODEL_KEY = "ai:active_model"
ACTIVE_MODEL_TTL = 300        # 5 minutes
FALLBACK_TTL = 30             # retry Supabase soon after an outage
KEY_CACHE_TTL = 60            # seconds; bounds how long a rotated key lingers
DEFAULT_TIMEOUT = 60.0

SUPPORTED_PROVIDERS = ("openai", "groq", "gemini", "anthropic")


class AIClientError(Exception):
    def __init__(self, message: str, fatal: bool = False):
        super().__init__(message)
        self.fatal = fatal


class UnsupportedProviderError(AIClientError):
    def __init__(self, provider: str):
        super().__init__(
            f"Unsupported AI provider '{provider}'. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}.",
            fatal=True,
        )


# ------------------------------------------------------------------ providers


class Provider:
    name = ""
    max_output_tokens = 4096  # hard cap per request for this provider's models

    async def generate(self, *, prompt: str, system_prompt: str, model: str,
                       api_key: str, temperature: float, max_tokens: int,
                       json_mode: bool, timeout: float) -> str:
        raise NotImplementedError

    async def _post(self, url: str, headers: dict, body: dict,
                    timeout: float) -> dict:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as e:
            logger.error("%s request failed: %s", self.name, type(e).__name__)
            raise AIClientError(f"{self.name} is unreachable") from None
        if resp.status_code != 200:
            # Provider error bodies can echo request details; log status only.
            logger.error("%s returned HTTP %s", self.name, resp.status_code)
            fatal = resp.status_code in (400, 401, 403, 404)
            raise AIClientError(
                f"{self.name} returned HTTP {resp.status_code}", fatal=fatal)
        try:
            return resp.json()
        except ValueError:
            raise AIClientError(f"{self.name} returned a non-JSON body") from None


class _OpenAICompatible(Provider):
    url = ""

    async def generate(self, *, prompt, system_prompt, model, api_key,
                       temperature, max_tokens, json_mode, timeout) -> str:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": min(max_tokens, self.max_output_tokens),
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        data = await self._post(
            self.url, {"Authorization": f"Bearer {api_key}"}, body, timeout)
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise AIClientError(f"{self.name} returned an unexpected response") from None


class OpenAIProvider(_OpenAICompatible):
    name = "openai"
    url = "https://api.openai.com/v1/chat/completions"
    max_output_tokens = 16000


class GroqProvider(_OpenAICompatible):
    name = "groq"
    url = "https://api.groq.com/openai/v1/chat/completions"
    max_output_tokens = 8000


class GeminiProvider(Provider):
    name = "gemini"
    max_output_tokens = 8192

    async def generate(self, *, prompt, system_prompt, model, api_key,
                       temperature, max_tokens, json_mode, timeout) -> str:
        config = {
            "temperature": temperature,
            "maxOutputTokens": min(max_tokens, self.max_output_tokens),
        }
        if json_mode:
            config["responseMimeType"] = "application/json"
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": config,
        }
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}
        data = await self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            {"x-goog-api-key": api_key}, body, timeout)
        try:
            parts = data["candidates"][0]["content"]["parts"]
            return "".join(p.get("text", "") for p in parts)
        except (KeyError, IndexError, TypeError):
            raise AIClientError("gemini returned an unexpected response") from None


class AnthropicProvider(Provider):
    name = "anthropic"
    max_output_tokens = 8192

    async def generate(self, *, prompt, system_prompt, model, api_key,
                       temperature, max_tokens, json_mode, timeout) -> str:
        # No native JSON mode; the prompt itself asks for JSON only.
        body = {
            "model": model,
            "max_tokens": min(max_tokens, self.max_output_tokens),
            "temperature": min(temperature, 1.0),
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            body["system"] = system_prompt
        data = await self._post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": api_key, "anthropic-version": "2023-06-01"},
            body, timeout)
        try:
            return "".join(b.get("text", "") for b in data["content"]
                           if b.get("type") == "text")
        except (KeyError, TypeError):
            raise AIClientError("anthropic returned an unexpected response") from None


_PROVIDERS = {
    "openai": OpenAIProvider,
    "groq": GroqProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
}


def get_provider(name: str) -> Provider:
    """Factory: the provider implementation for `name`."""
    cls = _PROVIDERS.get((name or "").strip().lower())
    if cls is None:
        raise UnsupportedProviderError(name)
    return cls()


# ------------------------------------------------------- runtime configuration

_key_cache: dict[str, tuple[float, Optional[str]]] = {}


async def invalidate_active_model() -> None:
    """Call after any change to ai_models so the next request re-reads it."""
    await cache_delete(ACTIVE_MODEL_KEY)


def invalidate_keys() -> None:
    """Call after any change to api_keys_config."""
    _key_cache.clear()


def _env_active_model() -> dict:
    return {"provider": settings.AI_PROVIDER.strip().lower(),
            "model_name": settings.AI_MODEL.strip()}


def _query_default_model():
    return (db.table("ai_models").select("provider,model_name")
            .eq("is_default", True).eq("is_active", True).limit(1).execute())


async def get_active_model() -> dict:
    """{'provider', 'model_name'} - Supabase default model, else the env one."""
    cached = await cache_get(ACTIVE_MODEL_KEY)
    if cached:
        return cached
    try:
        rows = (await asyncio.to_thread(_query_default_model)).data or []
    except Exception as e:
        logger.warning("Could not read ai_models (%s); using env model",
                       type(e).__name__)
        fallback = _env_active_model()
        await cache_set(ACTIVE_MODEL_KEY, fallback, FALLBACK_TTL)
        return fallback
    if not rows:
        # Table empty or nothing marked default: not an error, use the env.
        fallback = _env_active_model()
        await cache_set(ACTIVE_MODEL_KEY, fallback, FALLBACK_TTL)
        return fallback
    active = {"provider": rows[0]["provider"].strip().lower(),
              "model_name": rows[0]["model_name"]}
    await cache_set(ACTIVE_MODEL_KEY, active, ACTIVE_MODEL_TTL)
    return active


def _query_key(name: str):
    return (db.table("api_keys_config").select("key_value")
            .eq("key_name", name).limit(1).execute())


async def _db_key(name: str) -> Optional[str]:
    cached = _key_cache.get(name)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    value = None
    try:
        rows = (await asyncio.to_thread(_query_key, name)).data or []
        if rows:
            value = decrypt_secret(rows[0]["key_value"])
            if value is None:
                logger.error("Stored key %s cannot be decrypted "
                             "(was KEY_ENCRYPTION_SECRET changed?)", name)
    except Exception as e:
        logger.warning("Could not read api_keys_config (%s)", type(e).__name__)
        # Don't cache a failed read: the next call should try again.
        return None
    _key_cache[name] = (time.monotonic() + KEY_CACHE_TTL, value)
    return value


def key_names_for(provider: str) -> list[str]:
    """Key names that can serve `provider`, most specific first."""
    names = [f"{provider.upper()}_API_KEY"]
    if provider == settings.AI_PROVIDER.strip().lower():
        names.insert(0, "AI_API_KEY")  # the main key beats the provider-named one
    return names


def _env_key(name: str) -> str:
    return (getattr(settings, name, "") or "").strip()


async def resolve_api_key(provider: str) -> Optional[str]:
    for name in key_names_for(provider):
        value = await _db_key(name)
        if value:
            return value
    for name in key_names_for(provider):
        value = _env_key(name)
        if value:
            return value
    return None


# ----------------------------------------------------------------------- client


class AIClient:
    async def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        *,
        json_mode: bool = False,
        max_tokens: Optional[int] = None,
        timeout: float = DEFAULT_TIMEOUT,
        temperature: Optional[float] = None,
    ) -> str:
        """
        One completion from whichever model is active right now.
        max_tokens raises (never lowers) the AI_MAX_TOKENS floor, then is
        capped at the provider's own output limit. temperature overrides
        AI_TEMPERATURE for this call.
        """
        active = await get_active_model()
        provider = get_provider(active["provider"])  # raises if unsupported

        api_key = await resolve_api_key(provider.name)
        if not api_key:
            logger.error("No API key configured for provider %s", provider.name)
            raise AIClientError(
                f"No API key configured for '{provider.name}'.", fatal=True)

        return await provider.generate(
            prompt=prompt,
            system_prompt=system_prompt,
            model=active["model_name"],
            api_key=api_key,
            temperature=settings.AI_TEMPERATURE if temperature is None else temperature,
            max_tokens=max(settings.AI_MAX_TOKENS, max_tokens or 0),
            json_mode=json_mode,
            timeout=timeout,
        )


ai_client = AIClient()
