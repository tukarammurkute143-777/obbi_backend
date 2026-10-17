from pydantic import BaseModel, EmailStr, Field


class SendItineraryEmailRequest(BaseModel):
    email: EmailStr


class EditQueuedEmailRequest(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=2000)
