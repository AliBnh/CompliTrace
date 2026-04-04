from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
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


def _raw_upload_filename(request: Request, body: bytes) -> str | None:
    content_type = request.headers.get("content-type", "").lower()
    if "application/pdf" not in content_type and "application/octet-stream" not in content_type:
        return None
    if not body:
        return None
    return request.headers.get("x-filename", "upload.pdf")


@router.post("/documents", response_model=DocumentOut)
async def upload_document(
    request: Request,
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
) -> DocumentOut:
    if file is None:
        form = await request.form()
        maybe = form.get("file")
        if isinstance(maybe, UploadFile):
            file = maybe

    raw_body: bytes | None = None
    raw_filename: str | None = None
    if file is None:
        raw_body = await request.body()
        raw_filename = _raw_upload_filename(request, raw_body)

    if file is None and raw_filename is None:
        raise HTTPException(
            status_code=422,
            detail=(
                "Missing file upload. Send multipart/form-data with key 'file' "
                "or raw PDF body with Content-Type application/pdf and optional X-Filename."
            ),
        )

    resolved_filename = file.filename if file is not None else raw_filename
    if not resolved_filename or not resolved_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    safe_name = Path(resolved_filename).name
    stored_path = settings.uploads_dir / safe_name
    with stored_path.open("wb") as f:
        if raw_body is not None and file is None:
            f.write(raw_body)
        else:
            assert file is not None
            f.write(await file.read())

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
