from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime

class SendOTPRequest(BaseModel):
    mobile: str
    
class VerifyOTPRequest(BaseModel):
    mobile: str
    otp: str
    device_fingerprint: Optional[str] = None
    location: Optional[str] = None

class GoogleAuthRequest(BaseModel):
    token: str
    device_fingerprint: Optional[str] = None
    location: Optional[str] = None

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict
    is_new_user: bool

class RefreshTokenRequest(BaseModel):
    refresh_token: str

class UserResponse(BaseModel):
    id: str
    name: Optional[str]
    email: Optional[str]
    mobile: Optional[str]
    login_type: str
    location: Optional[str]
    is_new_user: bool
    created_at: datetime