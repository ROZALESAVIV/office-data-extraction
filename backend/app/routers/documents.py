"""Document upload and retrieval.

The lawyer drags in the referral email plus whatever came out of the insurer's
portal, in one go. Each file is identified by content, deduplicated, stored
under a key made only of UUIDs, and queued for extraction.
"""

import hashlib
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app import audit
from app.deps import TenantContext, get_current_user_with_tenant, require_write_role
from app.models.models import Case, Document, DocumentType
from app.schemas.documents import (
    DocumentOut,
    DocumentTypeOut,
    DocumentTypeUpdate,
    DocumentUrlOut,
)
from app.services import files, storage

router = APIRouter(tags=["documents"])

MAX_FILES_PER_UPLOAD = 40
MAX_FILE_BYTES = 40 * 1024 * 1024
# Cases in these states are finished; adding documents would change what was
# already submitted.
CLOSED_CASE_STATUSES = ("submitted", "closed")
SIGNED_URL_SECONDS = 900


def _get_case(ctx: TenantContext, case_id: uuid.UUID) -> Case:
    case = (
        ctx.db.query(Case)
        .filter(
            Case.id == case_id,
            Case.tenant_id == ctx.user.tenant_id,
            Case.deleted_at.is_(None),
        )
        .first()
    )
    if not case:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Case not found")
    return case


def _get_document(ctx: TenantContext, document_id: uuid.UUID) -> Document:
    doc = (
        ctx.db.query(Document)
        .filter(
            Document.id == document_id,
            Document.tenant_id == ctx.user.tenant_id,
            Document.deleted_at.is_(None),
        )
        .first()
    )
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return doc


def _read_capped(upload: UploadFile) -> bytes:
    """Read the whole file, aborting past the cap.

    Content-Length is a claim by the client, so the bytes are counted as they
    arrive rather than trusted up front.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = upload.file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_FILE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"{upload.filename or 'file'} exceeds {MAX_FILE_BYTES // (1024 * 1024)}MB",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _decorate(db: Session, doc: Document, duplicate: bool = False) -> DocumentOut:
    out = DocumentOut.model_validate(doc)
    out.duplicate = duplicate
    if doc.document_type_id:
        dt = db.get(DocumentType, doc.document_type_id)
        if dt:
            out.document_type_key = dt.type_key
            out.document_type_label = dt.label
            out.is_extractable = dt.is_extractable
    return out


@router.post(
    "/cases/{case_id}/documents",
    response_model=list[DocumentOut],
    status_code=status.HTTP_201_CREATED,
)
def upload_documents(
    case_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    files_in: list[UploadFile] = File(..., alias="files"),
    # Uploading is clerical work, so 'staff' may do it. Confirming extracted
    # values, re-classifying and deleting are not clerical and stay restricted.
    ctx: TenantContext = Depends(get_current_user_with_tenant),
):
    case = _get_case(ctx, case_id)
    if case.status in CLOSED_CASE_STATUSES:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Case is {case.status}; it accepts no new documents"
        )
    if len(files_in) > MAX_FILES_PER_UPLOAD:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"At most {MAX_FILES_PER_UPLOAD} files per upload",
        )

    results: list[DocumentOut] = []
    for upload in files_in:
        blob = _read_capped(upload)
        if not blob:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"{files.sanitize_filename(upload.filename)} is empty",
            )
        try:
            file_format = files.sniff_format(blob)
        except files.UnsupportedFile as exc:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"{files.sanitize_filename(upload.filename)}: {exc}",
            ) from exc

        digest = hashlib.sha256(blob).hexdigest()
        existing = (
            ctx.db.query(Document)
            .filter(
                Document.case_id == case.id,
                Document.content_sha256 == digest,
                Document.deleted_at.is_(None),
            )
            .first()
        )
        if existing:
            results.append(_decorate(ctx.db, existing, duplicate=True))
            continue

        page_count, text_extractable = None, False
        if file_format == "pdf":
            stats = files.pdf_stats(blob)
            page_count, text_extractable = stats.page_count, stats.text_extractable
        elif file_format in ("docx", "eml"):
            text_extractable = True

        doc = Document(
            tenant_id=ctx.user.tenant_id,
            case_id=case.id,
            file_name=files.sanitize_filename(upload.filename),
            storage_path="",  # set below, once the id exists
            file_format=file_format,
            mime_type=files.mime_for(file_format),
            file_size_bytes=len(blob),
            content_sha256=digest,
            text_extractable=text_extractable,
            page_count=page_count,
            processing_status="pending",
            uploaded_by=ctx.user.id,
        )
        ctx.db.add(doc)
        # flush, not commit: we need the generated id to build the storage key,
        # but nothing must be visible until the bytes are safely stored.
        ctx.db.flush()

        key = storage.build_key(ctx.user.tenant_id, case.id, doc.id, file_format)
        doc.storage_path = key
        if file_format == "pdf":
            doc.preview_storage_path = key

        try:
            storage.upload(key, blob, doc.mime_type)
        except storage.StorageError as exc:
            # Roll back so no row survives pointing at an object that is not
            # there.
            ctx.db.rollback()
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY, "Could not store the uploaded file"
            ) from exc

        audit.record(
            ctx.db,
            ctx.user,
            "document.uploaded",
            case_id=case.id,
            details={"file_name": doc.file_name, "format": file_format, "bytes": len(blob)},
        )
        try:
            ctx.db.commit()
        except Exception:
            ctx.db.rollback()
            # The bytes are stored but the row is gone; remove the orphan.
            try:
                storage.delete(key)
            except storage.StorageError:
                pass
            raise
        ctx.db.refresh(doc)
        results.append(_decorate(ctx.db, doc))

    return results


@router.get("/cases/{case_id}/documents", response_model=list[DocumentOut])
def list_documents(
    case_id: uuid.UUID, ctx: TenantContext = Depends(get_current_user_with_tenant)
):
    _get_case(ctx, case_id)
    docs = (
        ctx.db.query(Document)
        .filter(
            Document.case_id == case_id,
            Document.tenant_id == ctx.user.tenant_id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.uploaded_at)
        .all()
    )
    return [_decorate(ctx.db, d) for d in docs]


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID, ctx: TenantContext = Depends(get_current_user_with_tenant)
):
    return _decorate(ctx.db, _get_document(ctx, document_id))


@router.get("/documents/{document_id}/url", response_model=DocumentUrlOut)
def get_document_url(
    document_id: uuid.UUID, ctx: TenantContext = Depends(get_current_user_with_tenant)
):
    """A short-lived link for the review viewer.

    Loading the row through the tenant-scoped session IS the authorisation
    check. The storage key itself is never returned - it would expose the
    tenant/case layout of the bucket.
    """
    doc = _get_document(ctx, document_id)
    key = doc.preview_storage_path or doc.storage_path
    try:
        url = storage.signed_url(key, SIGNED_URL_SECONDS)
    except storage.StorageNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found in storage") from exc
    except storage.StorageError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not produce a link") from exc
    return DocumentUrlOut(url=url, expires_in_seconds=SIGNED_URL_SECONDS)


@router.get("/document-types", response_model=list[DocumentTypeOut])
def list_document_types(ctx: TenantContext = Depends(get_current_user_with_tenant)):
    """The catalogue, so the review screen can offer a re-classification."""
    return ctx.db.query(DocumentType).order_by(DocumentType.label).all()


@router.patch("/documents/{document_id}", response_model=DocumentOut)
def set_document_type(
    document_id: uuid.UUID,
    body: DocumentTypeUpdate,
    ctx: TenantContext = Depends(require_write_role),
):
    """Lawyer overrides the classification. Their choice is final."""
    doc = _get_document(ctx, document_id)
    doc_type = ctx.db.get(DocumentType, body.document_type_id)
    if doc_type is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown document type")
    before = doc.document_type_id
    doc.document_type_id = doc_type.id
    doc.document_type_source = "user"
    doc.document_type_confidence = None
    audit.record(
        ctx.db,
        ctx.user,
        "document.reclassified",
        case_id=doc.case_id,
        details={"from": str(before), "to": doc_type.type_key},
    )
    ctx.db.commit()
    ctx.db.refresh(doc)
    return _decorate(ctx.db, doc)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: uuid.UUID, ctx: TenantContext = Depends(require_write_role)
):
    """Soft delete. The stored object is kept: a case file is evidence."""
    doc = _get_document(ctx, document_id)
    doc.deleted_at = datetime.now(UTC)
    audit.record(
        ctx.db,
        ctx.user,
        "document.deleted",
        case_id=doc.case_id,
        details={"file_name": doc.file_name},
    )
    ctx.db.commit()
