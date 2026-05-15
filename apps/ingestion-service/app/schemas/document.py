from datetime import datetime

from pydantic import BaseModel


class SectionOut(BaseModel):
    id: str
    section_order: int
    section_title: str
    content: str
    page_start: int | None
    page_end: int | None

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    title: str
    filename: str
    status: str
    error_message: str | None
    created_at: datetime
    section_count: int = 0

    model_config = {"from_attributes": True}
