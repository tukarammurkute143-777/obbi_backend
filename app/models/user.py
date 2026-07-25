from typing import Optional

from pydantic import BaseModel, EmailStr, Field, model_validator


class UpdateProfileRequest(BaseModel):
    """
    Profile fields a user may change. `mobile` is deliberately absent — it is
    the OTP login identity, so changing it here would let someone take over
    another account's number without verification.
    """

    name: Optional[str] = Field(None, min_length=2, max_length=100)
    email: Optional[EmailStr] = None
    location: Optional[str] = Field(None, min_length=2, max_length=200)

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.name is None and self.email is None and self.location is None:
            raise ValueError("Kuch to bhejo — name, email ya location.")
        return self


class ProfileResponse(BaseModel):
    id: str
    name: Optional[str] = None
    email: Optional[str] = None
    mobile: Optional[str] = None
    login_type: Optional[str] = None
    location: Optional[str] = None
    is_new_user: Optional[bool] = None
    total_visits: Optional[int] = None
    last_login: Optional[str] = None
    created_at: Optional[str] = None
    is_owner: bool = False


class VisitEntry(BaseModel):
    ip_address: Optional[str] = None
    login_type: Optional[str] = None
    device_fingerprint: Optional[str] = None
    created_at: Optional[str] = None


class VisitHistoryResponse(BaseModel):
    total_visits: int
    successful_logins: int
    visits: list[VisitEntry]
