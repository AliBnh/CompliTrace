from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.document import Document, Section
from app.repositories.documents import create_document_with_sections
from app.schemas.document import DocumentOut, SectionOut
from app.services.parser import parse_pdf_into_sections


router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/documents", response_model=DocumentOut)
def upload_document(file: UploadFile = File(...), db: Session = Depends(get_db)) -> DocumentOut:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    safe_name = Path(file.filename).name
    stored_path = settings.uploads_dir / safe_name
    with stored_path.open("wb") as f:
        f.write(file.file.read())

    try:
        sections = parse_pdf_into_sections(str(stored_path))
        if not sections:
            raise ValueError("No sections detected")

        doc = create_document_with_sections(
            db,
            title=Path(safe_name).stem,
            filename=safe_name,
            parsed_sections=sections,
        )
    except Exception as exc:
        failed = Document(title=Path(safe_name).stem, filename=safe_name, status="failed", error_message=str(exc))
        db.add(failed)
        db.commit()
        db.refresh(failed)
        raise HTTPException(status_code=422, detail=f"Failed to parse PDF: {exc}")

    section_count = db.scalar(select(func.count()).select_from(Section).where(Section.document_id == doc.id)) or 0
    out = DocumentOut.model_validate(doc)
    out.section_count = int(section_count)
    return out


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: str, db: Session = Depends(get_db)) -> DocumentOut:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    section_count = db.scalar(select(func.count()).select_from(Section).where(Section.document_id == document_id)) or 0
    out = DocumentOut.model_validate(doc)
    out.section_count = int(section_count)
    return out


@router.get("/documents/{document_id}/sections", response_model=list[SectionOut])
def get_sections(document_id: str, db: Session = Depends(get_db)) -> list[SectionOut]:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    rows = db.scalars(
        select(Section).where(Section.document_id == document_id).order_by(Section.section_order.asc())
    ).all()
    return [SectionOut.model_validate(row) for row in rows]
