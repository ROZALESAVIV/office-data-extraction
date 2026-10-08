"""Classify a document, extract its fields, and resolve the case's answers.

Entry point is `run(document_id, tenant_id)`, queued as a background task when
a document is uploaded. It must never raise: FastAPI's BackgroundTasks swallows
exceptions silently, which would leave a document stuck in 'extracting' forever.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import SessionLocal, set_tenant
from app.models.models import (
    Case,
    CaseField,
    CaseFieldValue,
    Document,
    DocumentType,
    DocumentTypeField,
    FieldCandidate,
    Sender,
)
from app.reference.case_types import CASE_TYPE_CLAIM, canonical
from app.reference.deadlines import defence_deadline
from app.services import files, llm, referral_email, storage

log = logging.getLogger(__name__)

# Pages per extraction call. A scanned Hebrew page runs roughly 1,800 input
# tokens, so this stays well inside a request and keeps one failed window from
# costing the whole document.
PAGE_WINDOW = 20
# Three pages, not one. A pleading bundle often opens with the court's
# case-opening confirmation, so page 1 is not the document - page 2 is. Judging
# a 48-page pleading by its cover sheet filed it as "correspondence" and lost
# sixteen fields.
CLASSIFY_PAGES = 3
MAX_ATTEMPTS = 3
LEASE_MINUTES = 15

# Below this, the classifier's answer is not trusted and the document is left
# for a lawyer to label.
MIN_CLASSIFY_CONFIDENCE = 0.55

# A quote the model claimed but that is not on the page it named. Not proof of
# a wrong value - the page may be a scan with no text to check against - but
# enough to push the field towards review.
UNVERIFIED_SNIPPET_PENALTY = 0.30

# Documents longer than this get a navigation pass first: one cheap call that
# finds where the document's own content ends and the exhibits begin. A real
# pleading bundle is 3-5 pages of content followed by 40+ pages of attachments
# that are already in the case file separately.
NAVIGATE_ABOVE_PAGES = 8
NAVIGATE_SAMPLE_HEAD = 6
NAVIGATE_SAMPLE_TAIL = 2
# Never send more than this for extraction without a navigation result saying
# so. One sample file is 186 pages of damage photographs.
MAX_EXTRACT_PAGES = 40

# A rival has to be this close to the winner's confidence to count as a real
# disagreement rather than noise.
CONFLICT_CONFIDENCE_BAND = 0.15


@dataclass
class FieldSpec:
    field_id: uuid.UUID
    field_key: str
    label: str
    data_type: str
    priority: int
    hint: str | None


@dataclass
class ExtractionReport:
    document_id: uuid.UUID
    status: str
    candidates: int = 0
    cost_usd: float = 0.0
    error: str | None = None


# ── field specs ──────────────────────────────────────────────────────────────


def field_specs_for_type(db: Session, document_type_id: uuid.UUID) -> list[FieldSpec]:
    rows = (
        db.query(DocumentTypeField, CaseField)
        .join(CaseField, CaseField.id == DocumentTypeField.field_id)
        .filter(DocumentTypeField.document_type_id == document_type_id)
        .order_by(DocumentTypeField.priority, CaseField.sort_order)
        .all()
    )
    return [
        FieldSpec(
            field_id=cf.id,
            field_key=cf.field_key,
            label=cf.label,
            data_type=cf.data_type,
            priority=dtf.priority,
            hint=dtf.extraction_hint,
        )
        for dtf, cf in rows
    ]


def _field_list_prompt(specs: list[FieldSpec]) -> str:
    lines = ["Record these fields. Each line is: key | what it is | type", ""]
    for s in specs:
        line = f"- {s.field_key} | {s.label} | {s.data_type}"
        if s.hint:
            line += f" | {s.hint}"
        lines.append(line)
    return "\n".join(lines)


# ── classification ───────────────────────────────────────────────────────────


def classify(
    db: Session, doc: Document, blob: bytes, client: llm.LLMClient
) -> tuple[DocumentType | None, float, llm.LLMResult | None]:
    """Decide what the document is. The filename is a hint; the page decides."""
    types = db.query(DocumentType).filter(DocumentType.type_key != "other").all()
    by_key = {t.type_key: t for t in types}

    if doc.file_format == "eml":
        return by_key.get("referral_email"), 1.0, None

    catalogue = "\n".join(
        f"- {t.type_key} | {t.label}" + (f" | {t.description}" if t.description else "")
        for t in types
    )
    page = files.pdf_page_window(blob, 1, CLASSIFY_PAGES) if doc.file_format == "pdf" else blob
    total = doc.page_count or 0
    result = client.call_tool(
        system=llm.CLASSIFY_SYSTEM,
        content=[
            llm.pdf_block(page),
            llm.text_block(
                f"These are the first {CLASSIFY_PAGES} pages of a "
                f"{total or 'unknown'}-page document.\n"
                f"Filename as uploaded: {doc.file_name}\n\n"
                f"Known document types:\n{catalogue}"
            ),
        ],
        tool=llm.classification_tool(list(by_key)),
        max_tokens=1000,
        effort=llm.CLASSIFY_EFFORT,
    )
    key = result.data.get("type_key")
    confidence = llm.clamp_confidence(result.data.get("confidence"))
    if key == "unknown" or key not in by_key or confidence < MIN_CLASSIFY_CONFIDENCE:
        return None, confidence, result
    return by_key[key], confidence, result


# ── extraction ───────────────────────────────────────────────────────────────


def _sample_pages(total: int) -> list[int]:
    """First few pages, a couple from the end, plus a middle probe."""
    pages = list(range(1, min(NAVIGATE_SAMPLE_HEAD, total) + 1))
    if total > NAVIGATE_SAMPLE_HEAD + NAVIGATE_SAMPLE_TAIL:
        pages.append(total // 2)
    pages += list(range(max(1, total - NAVIGATE_SAMPLE_TAIL + 1), total + 1))
    return sorted(set(pages))


def locate_content(
    blob: bytes, total_pages: int, client: llm.LLMClient
) -> tuple[int, int, llm.LLMResult | None]:
    """Narrow a long document to the pages that carry its own content.

    Returns an inclusive 1-indexed range. On any doubt it widens rather than
    narrows: missing a page of the pleading costs real fields, while reading a
    couple of extra pages costs fractions of a cent.
    """
    if total_pages <= NAVIGATE_ABOVE_PAGES:
        return 1, total_pages, None

    sample = _sample_pages(total_pages)
    result = client.call_tool(
        system=llm.NAVIGATE_SYSTEM,
        content=[
            llm.pdf_block(files.pdf_subset(blob, sample)),
            llm.text_block(
                f"These are pages {sample} of a {total_pages}-page document, in that order."
            ),
        ],
        tool=llm.navigation_tool(),
        max_tokens=1500,
        effort=llm.CLASSIFY_EFFORT,
    )
    first = result.data.get("content_first_page") or 1
    last = result.data.get("content_last_page") or total_pages
    confidence = llm.clamp_confidence(result.data.get("confidence"))

    if confidence < MIN_CLASSIFY_CONFIDENCE:
        # Not sure where the content is: fall back to a capped prefix rather
        # than trusting a guess in either direction.
        return 1, min(total_pages, MAX_EXTRACT_PAGES), result

    first = max(1, min(int(first), total_pages))
    last = max(first, min(int(last), total_pages))
    if last - first + 1 > MAX_EXTRACT_PAGES:
        last = first + MAX_EXTRACT_PAGES - 1
    return first, last, result


@dataclass
class RawExtraction:
    field_key: str
    value: str | None
    confidence: float
    page: int | None
    snippet: str | None


def _extract_window(
    blob: bytes, specs: list[FieldSpec], first: int, last: int, client: llm.LLMClient
) -> tuple[list[RawExtraction], llm.LLMResult]:
    window = files.pdf_page_window(blob, first, last)
    result = client.call_tool(
        system=llm.EXTRACT_SYSTEM,
        content=[
            llm.pdf_block(window),
            llm.text_block(
                f"This is pages {first}-{last} of the document.\n\n"
                + _field_list_prompt(specs)
            ),
        ],
        tool=llm.extraction_tool([s.field_key for s in specs]),
        effort=llm.EXTRACT_EFFORT,
    )
    known = {s.field_key for s in specs}
    out = []
    for item in result.data.get("fields", []):
        key = item.get("field_key")
        if key not in known:
            # The enum should prevent this; drop it rather than trust it.
            log.warning("dropping unrequested field_key %r", key)
            continue
        page = item.get("page")
        out.append(
            RawExtraction(
                field_key=key,
                value=item.get("value"),
                confidence=llm.clamp_confidence(item.get("confidence")),
                # window-local page -> document page
                page=(first + page - 1) if isinstance(page, int) and page >= 1 else None,
                snippet=(item.get("snippet") or None),
            )
        )
    return out, result


def _from_referral_email(blob: bytes, specs: list[FieldSpec]) -> list[RawExtraction]:
    """Seven fields from a fixed template. Exact, free, no model involved."""
    parsed = referral_email.parse(blob)
    wanted = {s.field_key for s in specs}
    return [
        RawExtraction(field_key=k, value=v, confidence=1.0, page=1, snippet=v)
        for k, v in parsed.fields.items()
        if k in wanted and v
    ]


# ── persistence ──────────────────────────────────────────────────────────────


def _best_per_field(records: list[dict]) -> list[dict]:
    """Collapse to one record per field_key: field_candidates allows only one
    row per (document, field) - `uq_field_candidates_doc_field`.

    A long document is read in windows purely as a cost mechanic (PAGE_WINDOW),
    not because it says something different in each one. The same claim number
    stated near the top and repeated near the bottom is the same fact found
    twice, not two candidates - found as a live bug: two windows of one real
    48-page pleading both returned direct_claim_number, and inserting both
    violated the unique constraint and failed the *entire* document, losing
    every field it would otherwise have contributed.

    Kept: a verified snippet over an unverified one, then higher confidence,
    then the earlier page - the document's own heading is usually where a
    fact is stated authoritatively, a later repeat is corroboration.
    """
    best: dict[str, dict] = {}
    for r in records:
        key = r["field_key"]
        current = best.get(key)
        if current is None:
            best[key] = r
            continue
        rank = (bool(r["verified"]), r["confidence"], -(r["page"] or 1 << 30))
        current_rank = (
            bool(current["verified"]), current["confidence"], -(current["page"] or 1 << 30)
        )
        if rank > current_rank:
            best[key] = r
    return list(best.values())


def _persist_candidates(
    db: Session,
    doc: Document,
    extractions: list[RawExtraction],
    specs: dict[str, FieldSpec],
    page_text: dict[int, str],
    run_id: uuid.UUID,
) -> int:
    # Rewritten wholesale so a re-run is idempotent rather than cumulative.
    db.query(FieldCandidate).filter(FieldCandidate.document_id == doc.id).delete()

    prepared: list[dict] = []
    for item in extractions:
        if item.value in (None, ""):
            continue
        spec = specs[item.field_key]
        normalized = files.normalize_value(item.value, spec.data_type)
        if spec.field_key.endswith("_id"):
            normalized = files.normalize_id_number(item.value)
        elif spec.field_key == "court_city":
            # "תל אביב-יפו" and "תל אביב" are the same city under two names,
            # confirmed by the firm - fold them to one spelling so two documents
            # naming the same court don't read as a disagreement.
            normalized = files.canonical_city(normalized)
        if normalized is None:
            # The model produced something we cannot store as this type - a
            # date that is not a date, an amount with no digits.
            continue

        verified = None
        confidence = item.confidence
        if item.snippet and item.page and item.page in page_text and page_text[item.page].strip():
            verified = files.verify_snippet(item.snippet, page_text[item.page])
            if not verified:
                confidence = max(0.0, confidence - UNVERIFIED_SNIPPET_PENALTY)

        prepared.append(
            {
                "field_key": spec.field_key,
                "spec": spec,
                "value": normalized,
                "raw_value": item.value,
                "confidence": confidence,
                "page": item.page,
                "snippet": item.snippet,
                "verified": verified,
            }
        )

    written = 0
    for r in _best_per_field(prepared):
        spec = r["spec"]
        db.add(
            FieldCandidate(
                tenant_id=doc.tenant_id,
                case_id=doc.case_id,
                document_id=doc.id,
                field_id=spec.field_id,
                extraction_run_id=run_id,
                value=r["value"],
                raw_value=r["raw_value"],
                confidence=r["confidence"],
                source_page=r["page"],
                source_snippet=(r["snippet"] or "")[: llm.MAX_SNIPPET_CHARS] or None,
                snippet_verified=r["verified"],
                priority=spec.priority,
            )
        )
        written += 1
    return written


# ── resolution ───────────────────────────────────────────────────────────────

_RANKED_CANDIDATES = text("""
    SELECT fc.id, fc.field_id, fc.value, fc.confidence, fc.priority,
           fc.source_page, fc.source_snippet, fc.document_id, fc.snippet_verified
    FROM field_candidates fc
    JOIN documents d ON d.id = fc.document_id
    WHERE fc.case_id = :case_id
      AND fc.value IS NOT NULL
      AND d.deleted_at IS NULL
      AND d.processing_status IN ('extracted', 'partial')
    ORDER BY fc.field_id,
             fc.priority ASC,
             fc.confidence DESC,
             (fc.snippet_verified IS NOT FALSE) DESC,
             d.uploaded_at DESC,
             fc.id ASC
""")


def resolve_case_fields(db: Session, case_id: uuid.UUID, tenant_id: uuid.UUID) -> int:
    """Turn candidates into one answer per field.

    Locks the case first: documents uploaded together finish concurrently, and
    without the lock one resolution's conflict flags are lost.
    """
    db.execute(text("SELECT id FROM cases WHERE id = :c FOR UPDATE"), {"c": case_id})

    grouped: dict[uuid.UUID, list] = {}
    for row in db.execute(_RANKED_CANDIDATES, {"case_id": case_id}):
        grouped.setdefault(row.field_id, []).append(row)

    existing = {
        v.field_id: v
        for v in db.query(CaseFieldValue).filter(CaseFieldValue.case_id == case_id).all()
    }
    now = datetime.now(UTC)
    resolved = 0

    for field_id, rows in grouped.items():
        winner = rows[0]
        # A rival counts only if it is equally authoritative, or nearly as
        # confident. A receipt disagreeing weakly with a pleading is noise.
        rivals = [
            r
            for r in rows[1:]
            if r.value != winner.value
            and (
                r.priority == winner.priority
                or float(r.confidence) >= float(winner.confidence) - CONFLICT_CONFIDENCE_BAND
            )
        ]
        conflict_count = len({winner.value, *(r.value for r in rivals)}) if rivals else 0
        row = existing.get(field_id)

        if row is None:
            db.add(
                CaseFieldValue(
                    tenant_id=tenant_id,
                    case_id=case_id,
                    field_id=field_id,
                    extracted_value=winner.value,
                    value=winner.value,
                    source_document_id=winner.document_id,
                    source_page=winner.source_page,
                    source_snippet=winner.source_snippet,
                    confidence_score=winner.confidence,
                    resolved_candidate_id=winner.id,
                    has_conflict=bool(rivals),
                    conflict_count=conflict_count,
                    status="pending_review",
                    resolved_at=now,
                )
            )
            resolved += 1
        elif row.status == "pending_review" and row.reviewed_at is None:
            # Untouched by a lawyer, so a better source may still correct it.
            row.extracted_value = winner.value
            row.value = winner.value
            row.source_document_id = winner.document_id
            row.source_page = winner.source_page
            row.source_snippet = winner.source_snippet
            row.confidence_score = winner.confidence
            row.resolved_candidate_id = winner.id
            row.has_conflict = bool(rivals)
            row.conflict_count = conflict_count
            row.resolved_at = now
            resolved += 1
        else:
            # Confirmed, edited or rejected: the lawyer's answer stands. Only
            # flag that a later document disagrees with it.
            disagrees = winner.value != row.value
            row.has_conflict = disagrees
            row.conflict_count = 2 if disagrees else 0

    _compute_deadline(db, case_id, tenant_id, now)
    _populate_subrogation_plaintiff(db, case_id, tenant_id, now)
    return resolved


def _compute_deadline(db: Session, case_id: uuid.UUID, tenant_id: uuid.UUID, now) -> None:
    """Fill defence_deadline from whatever the case actually yielded.

    Computed, never extracted, and always flagged for review: court recess and
    granted extensions are not modelled, so this is an aid and not an authority.
    When no service date was found the clock starts at the court's filing date
    instead - earlier than the truth, which is the safe direction to be wrong.
    """
    fields = {cf.field_key: cf for cf in db.query(CaseField).all()}
    target = fields.get("defence_deadline")
    if target is None:
        return

    def value_of(key: str) -> str | None:
        cf = fields.get(key)
        if cf is None:
            return None
        row = (
            db.query(CaseFieldValue)
            .filter(CaseFieldValue.case_id == case_id, CaseFieldValue.field_id == cf.id)
            .first()
        )
        return row.value if row else None

    def number_of(key: str) -> float | None:
        raw = value_of(key)
        try:
            return float(raw) if raw else None
        except ValueError:
            return None

    stated = number_of("defence_days")
    result = defence_deadline(
        files.parse_iso_date(value_of("service_date")),
        value_of("court_procedure_type"),
        number_of("claim_amount"),
        int(stated) if stated else None,
        files.parse_iso_date(value_of("court_filing_date")),
    )
    if result is None:
        return

    iso = result.date.isoformat()
    row = (
        db.query(CaseFieldValue)
        .filter(CaseFieldValue.case_id == case_id, CaseFieldValue.field_id == target.id)
        .first()
    )
    if row is None:
        db.add(
            CaseFieldValue(
                tenant_id=tenant_id, case_id=case_id, field_id=target.id,
                extracted_value=iso, value=iso,
                # Counting from the filing date is an assumption, so it does not
                # get to look as certain as a date read off a stamp.
                confidence_score=0.5 if result.is_cautious else 0.9,
                status="pending_review", resolved_at=now,
            )
        )
    elif row.status == "pending_review" and row.reviewed_at is None:
        row.extracted_value = iso
        row.value = iso
        row.confidence_score = 0.5 if result.is_cautious else 0.9
        row.resolved_at = now


def _populate_subrogation_plaintiff(
    db: Session, case_id: uuid.UUID, tenant_id: uuid.UUID, now
) -> None:
    """In a claim (subrogation) case, plaintiff_1 is the referring insurer.

    Confirmed by the firm (2026-09-29): "Direct Insurance is registered as
    [the plaintiff] because it is the main recurring client [in] every one of
    its subrogation cases." That is a structural fact already known the moment
    the case is created - who referred it - not something to re-derive by
    reading a document. Computed here, the same way defence_deadline is:
    never extracted, and frozen the moment a lawyer has looked at the field
    (DECISIONS 7).

    Deliberately does NOT touch plaintiff_2 (the insured, only when the claim
    is also brought in their name) or any defendant field - those depend on
    the specific letter's content and the firm's own judgement, not on a fact
    this system already holds. They stay extracted from `subrogation_letter`
    instead (see DOCUMENT_TYPE_FIELDS).
    """
    fields = {cf.field_key: cf for cf in db.query(CaseField).all()}
    target = fields.get("plaintiff_1_name")
    case_type_field = fields.get("case_type")
    if target is None or case_type_field is None:
        return

    case_type_row = (
        db.query(CaseFieldValue)
        .filter(CaseFieldValue.case_id == case_id, CaseFieldValue.field_id == case_type_field.id)
        .first()
    )
    if case_type_row is None or canonical(case_type_row.value) != CASE_TYPE_CLAIM:
        return

    case = db.get(Case, case_id)
    if case is None or case.sender_id is None:
        return
    sender = db.get(Sender, case.sender_id)
    if sender is None:
        return

    row = (
        db.query(CaseFieldValue)
        .filter(CaseFieldValue.case_id == case_id, CaseFieldValue.field_id == target.id)
        .first()
    )
    if row is None:
        db.add(
            CaseFieldValue(
                tenant_id=tenant_id, case_id=case_id, field_id=target.id,
                extracted_value=sender.name, value=sender.name,
                # A structural fact, not an inference - as certain as a value
                # gets in this system.
                confidence_score=1.0, status="pending_review", resolved_at=now,
            )
        )
    elif row.status == "pending_review" and row.reviewed_at is None:
        row.extracted_value = sender.name
        row.value = sender.name
        row.confidence_score = 1.0
        row.resolved_at = now


# ── case status ──────────────────────────────────────────────────────────────

# Once a lawyer is working on a case, a newly uploaded document must not drag
# it back to 'extracting'.
_TERMINAL_CASE_STATUSES = ("in_review", "submitted", "closed")


def recompute_case_status(db: Session, case_id: uuid.UUID) -> None:
    case = db.get(Case, case_id)
    if case is None or case.status in _TERMINAL_CASE_STATUSES:
        return
    rows = (
        db.query(Document.processing_status)
        .filter(Document.case_id == case_id, Document.deleted_at.is_(None))
        .all()
    )
    statuses = [r[0] for r in rows]
    if not statuses:
        return
    if any(s in ("pending", "extracting") for s in statuses):
        case.status = "extracting"
    elif any(s in ("extracted", "partial") for s in statuses):
        case.status = "ready_for_review"
    elif all(s in ("failed", "skipped") for s in statuses):
        case.status = "failed"
    case.updated_at = datetime.now(UTC)


# ── entry point ──────────────────────────────────────────────────────────────


def _claim(db: Session, document_id: uuid.UUID) -> Document | None:
    """Take the lease, or decline if someone else holds it."""
    doc = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if doc is None or doc.deleted_at is not None:
        return None
    if doc.extraction_attempts >= MAX_ATTEMPTS:
        return None
    if doc.processing_status == "extracting":
        # Someone may still be working on it. Take over only once the lease has
        # expired - that is what the startup sweeper relies on.
        if doc.processing_started_at:
            age = datetime.now(UTC) - doc.processing_started_at
            if age.total_seconds() < LEASE_MINUTES * 60:
                return None
    elif doc.processing_status != "pending":
        # Already finished. Re-running is an explicit act (POST /reprocess sets
        # it back to 'pending'), so a duplicate background task or a retry
        # cannot silently redo work that has already been paid for.
        return None
    doc.processing_status = "extracting"
    doc.processing_started_at = datetime.now(UTC)
    doc.extraction_attempts += 1
    doc.extraction_run_id = uuid.uuid4()
    return doc


def run(
    document_id: uuid.UUID,
    tenant_id: uuid.UUID,
    client: llm.LLMClient | None = None,
) -> ExtractionReport:
    """Classify and extract one document. Never raises.

    BackgroundTasks discards exceptions without a trace, so an uncaught error
    here would leave the document 'extracting' until the sweeper notices.
    """
    report = ExtractionReport(document_id=document_id, status="failed")
    db = SessionLocal()
    try:
        set_tenant(db, str(tenant_id))
        doc = _claim(db, document_id)
        if doc is None:
            db.rollback()
            report.status = "skipped"
            return report
        case_id, run_id = doc.case_id, doc.extraction_run_id
        storage_key = doc.storage_path
        db.commit()  # publish the lease before the slow part

        blob = storage.download(storage_key)
        client = client or llm.AnthropicLLM()

        doc = db.get(Document, document_id)
        doc_type, confidence, cls_result = classify(db, doc, blob, client)
        if cls_result:
            report.cost_usd += cls_result.cost_usd
        doc.document_type_id = doc_type.id if doc_type else None
        doc.document_type_confidence = confidence
        doc.document_type_source = "ai"

        if doc_type is None or not doc_type.is_extractable:
            # Stored and forwarded to Odcanit, never read. Most of a claim file
            # is photographs, and this is where the cost saving comes from.
            doc.processing_status = "skipped"
            doc.processed_at = datetime.now(UTC)
            recompute_case_status(db, case_id)
            db.commit()
            report.status = "skipped"
            return report

        specs = field_specs_for_type(db, doc_type.id)
        if not specs:
            doc.processing_status = "skipped"
            doc.processed_at = datetime.now(UTC)
            recompute_case_status(db, case_id)
            db.commit()
            report.status = "skipped"
            return report

        extractions: list[RawExtraction] = []
        failures = 0
        windows = 0
        page_text: dict[int, str] = {}

        if doc.file_format == "eml":
            extractions = _from_referral_email(blob, specs)
            windows = 1
        else:
            page_text = files.pdf_page_text(blob) if doc.text_extractable else {}
            total = doc.page_count or files.pdf_stats(blob).page_count

            # A pleading bundle is a handful of content pages followed by
            # dozens of exhibits that already exist in the case separately.
            # Find the content first; sending the exhibits costs money and
            # invites the model to pull values out of the wrong document.
            content_first, content_last, nav = locate_content(blob, total, client)
            if nav:
                report.cost_usd += nav.cost_usd
                log.info(
                    "document %s: content pages %s-%s of %s",
                    doc.id, content_first, content_last, total,
                )

            for first in range(content_first, content_last + 1, PAGE_WINDOW):
                last = min(first + PAGE_WINDOW - 1, content_last)
                windows += 1
                try:
                    found, result = _extract_window(blob, specs, first, last, client)
                    extractions.extend(found)
                    report.cost_usd += result.cost_usd
                except llm.LLMError as exc:
                    # One bad window must not discard the pages that worked.
                    failures += 1
                    log.warning("window %s-%s failed on %s: %s", first, last, doc.id, exc)

        if failures and failures == windows:
            raise llm.LLMError(f"all {windows} extraction windows failed")

        report.candidates = _persist_candidates(
            db, doc, extractions, {s.field_key: s for s in specs}, page_text, run_id
        )
        doc.processing_status = "partial" if failures else "extracted"
        doc.processed_at = datetime.now(UTC)
        doc.error_message = f"{failures} of {windows} page windows failed" if failures else None
        db.flush()

        resolve_case_fields(db, case_id, tenant_id)
        recompute_case_status(db, case_id)
        db.commit()
        report.status = doc.processing_status
        return report

    except Exception as exc:
        log.exception("extraction failed for %s", document_id)
        report.error = str(exc)[:500]
        db.rollback()
        _mark_failed(document_id, tenant_id, report.error)
        return report
    finally:
        db.close()


def _mark_failed(document_id: uuid.UUID, tenant_id: uuid.UUID, message: str | None) -> None:
    """Record the failure on a fresh session - the original may be poisoned."""
    db = SessionLocal()
    try:
        set_tenant(db, str(tenant_id))
        doc = db.get(Document, document_id)
        if doc is not None:
            doc.processing_status = "failed"
            doc.error_message = message
            doc.processed_at = datetime.now(UTC)
            recompute_case_status(db, doc.case_id)
            db.commit()
    except Exception:
        log.exception("could not mark %s failed", document_id)
        db.rollback()
    finally:
        db.close()


def recover_stalled(max_age_minutes: int = LEASE_MINUTES) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Return documents whose job died mid-run, so they can be re-queued.

    Runs at startup, when no tenant context exists - the one sanctioned use of
    the admin connection. Documents that have already failed MAX_ATTEMPTS times
    are left alone, or a poisoned file loops forever on every restart.
    """
    from app.core.database import admin_session

    with admin_session() as db:
        locked = db.execute(
            text("SELECT pg_try_advisory_lock(hashtext('extraction_sweeper'))")
        ).scalar()
        if not locked:
            return []
        rows = db.execute(
            text(
                "UPDATE documents SET processing_status = 'pending', processing_started_at = NULL "
                "WHERE processing_status = 'extracting' "
                "  AND processing_started_at < now() - make_interval(mins => :m) "
                f"  AND extraction_attempts < {MAX_ATTEMPTS} "
                "RETURNING id, tenant_id"
            ),
            {"m": max_age_minutes},
        ).all()
        db.commit()
        return [(r.id, r.tenant_id) for r in rows]
