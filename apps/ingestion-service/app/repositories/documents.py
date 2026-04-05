from sqlalchemy.orm import Session

from app.models.document import Document, Section
from app.services.parser import ParsedSection


def create_document_with_sections(
    db: Session,
    *,
    title: str,
    filename: str,
    parsed_sections: list[ParsedSection],
) -> Document:
    document = Document(title=title, filename=filename, status="parsed")
    db.add(document)
    db.flush()

    for sec in parsed_sections:
        db.add(
            Section(
                document_id=document.id,
                section_order=sec.section_order,
                section_title=sec.section_title,
                content=sec.content,
                page_start=sec.page_start,
                page_end=sec.page_end,
            )
        )

    db.commit()
    db.refresh(document)
    return document
