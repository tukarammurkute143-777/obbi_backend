from typing import Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    # A UUID from an earlier reply; leave out to start a new conversation.
    session_id: Optional[str] = Field(
        None, pattern=r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
    # Leave out to auto-detect from the message.
    language: Optional[Literal["hindi", "marathi", "english", "hinglish"]] = None
