from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field, model_validator

BOOKING_STATUSES = ("pending", "confirmed", "ongoing", "completed", "cancelled")
PAYMENT_STATUSES = ("pending", "partial", "paid", "refunded")
PAYMENT_MODES = ("cash", "upi", "card", "bank_transfer", "pending")


class BookingCreate(BaseModel):
    customer_name: str = Field(..., min_length=2, max_length=100)
    customer_mobile: str = Field(..., pattern=r"^[6-9]\d{9}$")
    customer_email: Optional[EmailStr] = None

    route_from: str = Field(..., min_length=2, max_length=120)
    route_to: str = Field(..., min_length=2, max_length=120)
    pickup_date: date
    drop_date: Optional[date] = None

    vehicle_type: str = Field(..., min_length=2, max_length=60)
    driver_name: Optional[str] = Field(None, max_length=100)

    total_rate: float = Field(..., ge=0)
    advance_paid: float = Field(0, ge=0)
    extra_charges: float = Field(0, ge=0)
    all_inclusive: bool = False
    payment_mode: Literal[PAYMENT_MODES] = "pending"  # type: ignore[valid-type]

    is_partner_vehicle: bool = False
    partner_name: Optional[str] = Field(None, max_length=100)
    partner_mobile: Optional[str] = Field(None, pattern=r"^[6-9]\d{9}$")
    partner_commission: float = Field(0, ge=0)

    notes: Optional[str] = None

    @model_validator(mode="after")
    def check_dates_and_money(self):
        if self.drop_date and self.drop_date < self.pickup_date:
            raise ValueError("drop_date pickup_date se pehle nahi ho sakti.")

        billable = self.total_rate + self.extra_charges
        if self.advance_paid > billable:
            raise ValueError(
                "advance_paid total_rate + extra_charges se zyada nahi ho sakta."
            )

        if self.is_partner_vehicle and not self.partner_name:
            raise ValueError("Partner vehicle ke liye partner_name chahiye.")

        return self


class BookingUpdate(BaseModel):
    """Every field optional — this is a PATCH-style partial update over PUT."""

    customer_name: Optional[str] = Field(None, min_length=2, max_length=100)
    customer_mobile: Optional[str] = Field(None, pattern=r"^[6-9]\d{9}$")
    customer_email: Optional[EmailStr] = None

    route_from: Optional[str] = Field(None, min_length=2, max_length=120)
    route_to: Optional[str] = Field(None, min_length=2, max_length=120)
    pickup_date: Optional[date] = None
    drop_date: Optional[date] = None

    vehicle_type: Optional[str] = Field(None, min_length=2, max_length=60)
    driver_name: Optional[str] = Field(None, max_length=100)

    total_rate: Optional[float] = Field(None, ge=0)
    advance_paid: Optional[float] = Field(None, ge=0)
    extra_charges: Optional[float] = Field(None, ge=0)
    all_inclusive: Optional[bool] = None
    payment_mode: Optional[Literal[PAYMENT_MODES]] = None  # type: ignore[valid-type]
    payment_status: Optional[Literal[PAYMENT_STATUSES]] = None  # type: ignore[valid-type]

    is_partner_vehicle: Optional[bool] = None
    partner_name: Optional[str] = Field(None, max_length=100)
    partner_mobile: Optional[str] = Field(None, pattern=r"^[6-9]\d{9}$")
    partner_commission: Optional[float] = Field(None, ge=0)

    notes: Optional[str] = None
    status: Optional[Literal[BOOKING_STATUSES]] = None  # type: ignore[valid-type]

    @model_validator(mode="after")
    def at_least_one_field(self):
        if not self.model_dump(exclude_none=True):
            raise ValueError("Update ke liye kam se kam ek field bhejo.")
        return self
