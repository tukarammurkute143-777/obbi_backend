from typing import Literal

from pydantic import BaseModel, Field

Provider = Literal["openai", "groq", "gemini", "anthropic"]
KeyName = Literal[
    "AI_API_KEY", "OPENAI_API_KEY", "GROQ_API_KEY",
    "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
]


class UpdateKeyRequest(BaseModel):
    key_name: KeyName
    key_value: str = Field(min_length=8, max_length=500)


class AddModelRequest(BaseModel):
    provider: Provider
    model_name: str = Field(min_length=1, max_length=100,
                            pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/\-]*$")
    display_name: str = Field(min_length=1, max_length=100)
