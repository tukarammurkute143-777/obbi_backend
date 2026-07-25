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
    GOOGLE_MAPS_API_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379"
    RESEND_API_KEY: str = ""
    APP_ENV: str = "development"
    FRONTEND_URL: str = "http://localhost:3000"
    OWNER_PHONE: str = ""
    OWNER_EMAIL: str = ""

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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()