"""
Global guardrails: input checks for every request, output checks for AI replies.

InputGuardrails  - SQL-injection, prompt-injection, XSS and length checks.
OutputGuardrails - PII masking, content filtering, confidence flag, JSON parsing.

A note on the SQL check: all database access goes through Supabase's
parameterized PostgREST API, so values are never spliced into SQL and this
check is defence in depth, not the primary protection. It therefore matches
SQL *statements* ("drop table", "union select", "'; delete from") instead of
bare keywords. Rejecting the word "drop" or a ";" outright would refuse
ordinary cab requests such as "drop me at the airport; two bags".
"""

import html
import json
import re
from typing import Any, Optional

MAX_STRING_LENGTH = 500
MAX_TEXT_LENGTH = 2000

# Free-text fields that get the longer limit.
TEXT_FIELDS = frozenset({
    "message", "text", "special_requests", "notes", "comment", "comments",
    "description", "content", "body", "feedback", "query", "prompt",
})

# Credentials and opaque identifiers: never rewritten, never length-limited.
# Encoding a token or fingerprint would corrupt it, and a Google ID token is
# well over 500 characters.
SKIP_FIELDS = frozenset({
    "token", "id_token", "access_token", "refresh_token", "otp", "password",
    "device_fingerprint",
})

INVALID_INPUT = "Invalid input detected"
PRICING_FALLBACK = "Pricing ke liye kripya Obii Cabs office se sampark karein."
SAFE_FALLBACK = "Yeh jaankari abhi available nahi hai. Kripya Obii Cabs se sampark karein."


class GuardrailError(ValueError):
    """Raised when AI output cannot be turned into valid structured data."""


# ----------------------------------------------------------------------- input

_SQL_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"\bunion\s+(all\s+)?select\b",
    r"\bselect\s+(\*|[\w.,\s()`\"]+?)\s+from\s+[\w.`\"]+",
    r"\binsert\s+into\b",
    r"\bdelete\s+from\b",
    r"\bdrop\s+(table|database|schema|column|index|view)\b",
    r"\b(truncate|alter)\s+table\b",
    r"\bupdate\s+\w+\s+set\b",
    r";\s*(drop|select|insert|update|delete|alter|create|truncate|exec)\b",
    r"['\"]\s*(or|and)\s+['\"\w]+\s*=\s*['\"\w]+",   # ' OR '1'='1
    r"['\"]\s*--",                                    # quote, then comment
    r";\s*--",
    r"/\*.*?\*/",
)]

_PROMPT_PATTERNS = [re.compile(p, re.IGNORECASE) for p in (
    r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)",
    r"disregard\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)",
    r"forget\s+(all\s+|your\s+|the\s+)?(previous\s+)?(instructions|rules)",
    r"you\s+are\s+now\b",
    r"jailbreak",
    r"new\s+instructions",
    r"system\s+prompt",
)]
# Case-sensitive on purpose, so the name "Dan" is not rejected.
_DAN = re.compile(r"\bDAN\b")

_SCRIPT_BLOCK = re.compile(r"<\s*(script|style)\b[^>]*>.*?<\s*/\s*\1\s*>",
                           re.IGNORECASE | re.DOTALL)
_TAG = re.compile(r"<[^>]*>")


class InputGuardrails:

    def check_injection(self, text: str) -> bool:
        """True if the text looks like a SQL injection attempt."""
        return isinstance(text, str) and any(p.search(text) for p in _SQL_PATTERNS)

    def check_prompt_injection(self, text: str) -> bool:
        """True if the text looks like a prompt-injection attempt."""
        if not isinstance(text, str):
            return False
        return bool(_DAN.search(text)) or any(p.search(text) for p in _PROMPT_PATTERNS)

    def clean_string(self, text: str) -> str:
        """
        Strip HTML tags, then encode < > & " '. Unescaping first makes this
        idempotent, so input already sanitized upstream is not double-encoded.
        """
        text = _SCRIPT_BLOCK.sub("", html.unescape(text))
        text = _TAG.sub("", text)
        return html.escape(text, quote=True)

    def sanitize(self, data: Any) -> Any:
        """Recursively clean every string value; keys and non-strings are kept."""
        if isinstance(data, str):
            return self.clean_string(data)
        if isinstance(data, dict):
            return {
                k: v if k in SKIP_FIELDS else self.sanitize(v)
                for k, v in data.items()
            }
        if isinstance(data, list):
            return [self.sanitize(v) for v in data]
        return data

    def limit_for(self, field: Optional[str]) -> int:
        return MAX_TEXT_LENGTH if field in TEXT_FIELDS else MAX_STRING_LENGTH

    def find_length_violation(self, data: Any, field: Optional[str] = None
                              ) -> Optional[tuple[str, int]]:
        """(field, limit) of the first over-long string, else None."""
        if isinstance(data, str):
            limit = self.limit_for(field)
            return (field or "value", limit) if len(data) > limit else None
        if isinstance(data, dict):
            for k, v in data.items():
                if k in SKIP_FIELDS:
                    continue
                found = self.find_length_violation(v, k)
                if found:
                    return found
        elif isinstance(data, list):
            for v in data:
                found = self.find_length_violation(v, field)
                if found:
                    return found
        return None

    def validate_length(self, data: dict) -> bool:
        return self.find_length_violation(data) is None

    def find_attack(self, data: Any) -> bool:
        """True if any string in the structure trips an injection check."""
        if isinstance(data, str):
            return self.check_injection(data) or self.check_prompt_injection(data)
        if isinstance(data, dict):
            return any(self.find_attack(v) for k, v in data.items()
                       if k not in SKIP_FIELDS)
        if isinstance(data, list):
            return any(self.find_attack(v) for v in data)
        return False


# ---------------------------------------------------------------------- output

_CARD = re.compile(r"(?<!\d)\d{4}[\s-]\d{4}[\s-]\d{4}[\s-]\d{4}(?!\d)")
_AADHAAR = re.compile(r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)")

_COMPETITORS = re.compile(
    r"\b(ola|uber|rapido|blusmart|savaari|zoomcar|indrive|meru\s+cabs?|"
    r"mega\s+cabs?|easy\s+cabs?|carzonrent|revv|gozo\s*cabs?|quick\s*ride)\b",
    re.IGNORECASE,
)

# Currency amounts in either order: "₹5,000", "Rs. 500", "INR 2000", "500 rupees".
# The words "price"/"rates" alone are fine ("contact Obii Cabs for rates").
_PRICING = re.compile(
    r"(₹|\brs\.?|\binr\b|\brupees?\b|\$|\busd\b)\s*\d"
    r"|\d[\d,]*(\.\d+)?\s*(₹|/-|\brs\b\.?|\binr\b|\brupees?\b)",
    re.IGNORECASE,
)

# Deliberately short; extend as real cases turn up.
_OFFENSIVE = re.compile(
    r"\b(fuck\w*|shit\w*|bastard|bitch|asshole|madarchod|bhenchod|"
    r"behenchod|chutiya|gandu|randi)\b",
    re.IGNORECASE,
)

CONFIDENCE_FLAG_BELOW = 0.7


class OutputGuardrails:

    def check_pii(self, text: str) -> str:
        """Mask card and Aadhaar numbers with ****."""
        text = _CARD.sub("****", text)   # card first: its digit groups overlap
        return _AADHAAR.sub("****", text)

    def has_pricing(self, text: str) -> bool:
        return bool(_PRICING.search(text))

    def check_content(self, text: str) -> str:
        """The text, or a safe fallback if it names a competitor, quotes a
        price or is offensive."""
        if _PRICING.search(text):
            return PRICING_FALLBACK
        if _COMPETITORS.search(text) or _OFFENSIVE.search(text):
            return SAFE_FALLBACK
        return text

    def validate_json(self, text: str) -> dict:
        """Parse a model reply as a JSON object. Raises GuardrailError."""
        if not isinstance(text, str) or not text.strip():
            raise GuardrailError("empty response")
        body = text.strip()
        fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", body, re.DOTALL | re.IGNORECASE)
        if fence:
            body = fence.group(1)
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as e:
            raise GuardrailError(f"invalid JSON: {e.msg}") from None
        if not isinstance(parsed, dict):
            raise GuardrailError("JSON root must be an object")
        return parsed

    def flag_low_confidence(self, data: Any) -> Any:
        """Add low_confidence=true beside any confidence_score below 0.7."""
        if isinstance(data, dict):
            score = data.get("confidence_score")
            if isinstance(score, (int, float)) and not isinstance(score, bool) \
                    and score < CONFIDENCE_FLAG_BELOW:
                data["low_confidence"] = True
            for v in data.values():
                self.flag_low_confidence(v)
        elif isinstance(data, list):
            for v in data:
                self.flag_low_confidence(v)
        return data

    def process(self, data: Any) -> Any:
        """Apply PII masking and content filtering to every string, and the
        confidence flag to the whole structure."""
        cleaned = self._walk(data)
        return self.flag_low_confidence(cleaned)

    def _walk(self, data: Any) -> Any:
        if isinstance(data, str):
            return self.check_content(self.check_pii(data))
        if isinstance(data, dict):
            return {k: self._walk(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self._walk(v) for v in data]
        return data


input_guardrails = InputGuardrails()
output_guardrails = OutputGuardrails()
