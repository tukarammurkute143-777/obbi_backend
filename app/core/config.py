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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()