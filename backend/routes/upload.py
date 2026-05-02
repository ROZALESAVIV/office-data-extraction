from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from pathlib import Path
from typing import Optional

from database import get_db
from models.models import Case, Document, AuditLog
from services import storage_adapter
from config import settings

router = APIRouter()

MAX_BYTES = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024


# ── Cases ──────────────────────────────────────────────────────────────────────

@router.post("/cases", status_code=201)
def create_case(
    office_id: str = Form(...),
    created_by: str = Form(...),
    case_type: str = Form(...),
    client_name: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    case = Case(
        office_id=office_id,
        created_by=created_by,
        case_type=case_type,
        client_name=client_name,
        status="uploading",
    )
    db.add(case)

    db.add(AuditLog(
        office_id=office_id,
        user_id=created_by,
        document_id=None,
        action="case_created",
        details=f"case_type={case_type}",
    ))

    db.commit()
    db.refresh(case)
    return {"case_id": case.id, "status": case.status}


# ── Document upload ────────────────────────────────────────────────────────────

@router.post("/upload/{case_id}", status_code=201)
async def upload_document(
    case_id: str,
    file: UploadFile = File(...),
    office_id: str = Form(...),
    uploaded_by: str = Form(...),
    document_type: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    # Validate case belongs to this office
    case = db.query(Case).filter(
        Case.id == case_id,
        Case.office_id == office_id,
    ).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Validate content type
    if file.content_type not in ("application/pdf",):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    content = await file.read()

    # Validate size
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit",
        )

    storage_path = storage_adapter.save(content, file.filename or "upload.pdf", office_id)

    doc = Document(
        office_id=office_id,
        case_id=case_id,
        uploaded_by=uploaded_by,
        original_filename=file.filename or "upload.pdf",
        storage_path=storage_path,
        document_type=document_type,
        status="uploaded",
    )
    db.add(doc)

    db.add(AuditLog(
        office_id=office_id,
        user_id=uploaded_by,
        document_id=None,  # filled after flush
        action="uploaded",
        details=f"filename={file.filename}, document_type={document_type}",
    ))

    db.commit()
    db.refresh(doc)

    return {
        "document_id": doc.id,
        "case_id": case_id,
        "original_filename": doc.original_filename,
        "document_type": doc.document_type,
        "storage_path": doc.storage_path,
        "file_url": storage_adapter.get_url(doc.storage_path),
        "status": doc.status,
    }


# ── File serving ───────────────────────────────────────────────────────────────

@router.get("/files/{file_path:path}")
def serve_file(file_path: str, office_id: str, db: Session = Depends(get_db)):
    """Serve a stored PDF after confirming it belongs to the requesting office."""
    doc = db.query(Document).filter(
        Document.storage_path == file_path,
        Document.office_id == office_id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="File not found")

    full_path = Path(file_path)
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="File missing from storage")

    return FileResponse(str(full_path), media_type="application/pdf")
