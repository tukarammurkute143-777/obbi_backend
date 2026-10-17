from typing import Optional

from pydantic import BaseModel, Field, model_validator


class UpdateBlogRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    content: Optional[str] = Field(None, min_length=1, max_length=60000)

    @model_validator(mode="after")
    def _something_to_change(self):
        if self.title is None and self.content is None:
            raise ValueError("title ya content do")
        return self
