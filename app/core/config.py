from pydantic_settings import BaseSettings
from pydantic import field_validator

class Settings(BaseSettings):
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_KEY: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 15
    JWT_REFRESH_EXPIRE_DAYS: int = 7
    OPENAI_API_KEY: str = ""

    # AI provider. These are the *fallback* values: the active model is read
    # from the Supabase `ai_models` table at runtime, and keys saved through
    # the dashboard (`api_keys_config`) take precedence over these.
    # AI_PROVIDER: openai | groq | gemini | anthropic
    AI_PROVIDER: str = "openai"
    AI_MODEL: str = "gpt-4o"
    AI_API_KEY: str = ""
    AI_TEMPERATURE: float = 0.3
    AI_MAX_TOKENS: int = 4000
    # Per-provider keys, used when the active model's provider differs from
    # AI_PROVIDER (OPENAI_API_KEY above is the openai one).
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    # Encrypts keys stored in `api_keys_config`. Falls back to JWT_SECRET_KEY;
    # set it separately so rotating JWTs does not orphan the stored keys.
    KEY_ENCRYPTION_SECRET: str = ""
    GOOGLE_MAPS_API_KEY: str = ""
    TAVILY_API_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379"
    RESEND_API_KEY: str = ""
    # The sending domain must be verified in Resend or every send is rejected.
    EMAIL_FROM: str = "Obii Cabs <info@obiicabs.com>"
    APP_ENV: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    OWNER_PHONE: str = ""
    OWNER_EMAIL: str = ""

    # Twilio WhatsApp OTP delivery. TWILIO_WHATSAPP_FROM is the sender in
    # Twilio's format, e.g. "whatsapp:+14155238886" (sandbox number).
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_WHATSAPP_FROM: str = ""

    # OAuth client ID from Google Cloud Console. REQUIRED for /api/auth/google:
    # google-auth only verifies a token's audience when one is supplied, so
    # leaving this blank would accept ID tokens minted for any other Google app.
    # The endpoint refuses to run rather than skip that check.
    GOOGLE_CLIENT_ID: str = ""

    # Rate limiting — "memory://" is per-process. Point this at REDIS_URL
    # (e.g. "redis://localhost:6379") once running more than one worker,
    # otherwise each worker keeps its own separate counters.
    RATE_LIMIT_STORAGE_URI: str = "memory://"
    RATE_LIMIT_GENERAL: str = "100/minute"
    RATE_LIMIT_SEND_OTP: str = "3/hour"
    RATE_LIMIT_VERIFY_OTP: str = "5/hour"
    # Each uncached /api/safar call bills Google Maps, so cap it below the default.
    RATE_LIMIT_SAFAR: str = "30/minute"
    # Per user (JWT subject, else IP), on top of RATE_LIMIT_GENERAL.
    RATE_LIMIT_USER_HOUR: str = "100/hour"
    # LLM-backed endpoints (each call costs real money).
    RATE_LIMIT_AI: str = "10/hour"
    # Emails sent on a customer's request (to any address they type in).
    RATE_LIMIT_EMAIL: str = "5/hour"
    # Safar chat messages (some of them cost a model call).
    RATE_LIMIT_CHAT: str = "20/minute"
    # Public, unauthenticated pages (blogs): generous, since crawlers read them.
    RATE_LIMIT_PUBLIC: str = "120/minute"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()