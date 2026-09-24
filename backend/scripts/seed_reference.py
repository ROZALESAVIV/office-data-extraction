"""Load the global reference data: document types, case fields, and the mapping.

These three tables are product configuration, not per-tenant data, and they will
change as the firm refines what it extracts. That is why this is an idempotent
script rather than a data migration: re-running it updates rows in place and
removes mappings that were deleted from the reference files.

It never deletes a case_field or document_type that is already referenced by
real case data - that would orphan a lawyer's confirmed values.

Usage: python -m scripts.seed_reference
"""

import sys

from sqlalchemy import text

from app.core.database import admin_session
from app.models.models import CaseField, DocumentType, DocumentTypeField
from app.reference.case_fields import CASE_FIELDS, DOCUMENT_TYPE_FIELDS
from app.reference.document_types import DOCUMENT_TYPES


def main() -> int:
    with admin_session() as db:
        try:
            created = updated = 0
            for type_key, label, extractable, hints, desc in DOCUMENT_TYPES:
                row = db.query(DocumentType).filter(DocumentType.type_key == type_key).first()
                if row is None:
                    db.add(DocumentType(
                        type_key=type_key, label=label, is_extractable=extractable,
                        filename_hints=hints or None, description=desc,
                    ))
                    created += 1
                else:
                    row.label, row.is_extractable = label, extractable
                    row.filename_hints, row.description = hints or None, desc
                    updated += 1
            db.flush()
            print(f"document_types:      {created} created, {updated} updated")

            created = updated = 0
            for field_key, label, data_type, required, sort_order, always_review in CASE_FIELDS:
                row = db.query(CaseField).filter(CaseField.field_key == field_key).first()
                if row is None:
                    db.add(CaseField(
                        field_key=field_key, label=label, data_type=data_type,
                        is_required=required, sort_order=sort_order,
                        always_needs_review=always_review,
                    ))
                    created += 1
                else:
                    row.label, row.data_type = label, data_type
                    row.is_required, row.sort_order = required, sort_order
                    row.always_needs_review = always_review
                    updated += 1
            db.flush()
            print(f"case_fields:         {created} created, {updated} updated")

            types = {t.type_key: t.id for t in db.query(DocumentType).all()}
            fields = {f.field_key: f.id for f in db.query(CaseField).all()}

            # Rebuild the mapping wholesale: it is pure configuration with no
            # rows pointing at it, so a clean replace keeps it in step with the
            # reference file instead of accumulating stale entries.
            db.execute(text("DELETE FROM document_type_fields"))
            n = 0
            for type_key, entries in DOCUMENT_TYPE_FIELDS.items():
                for field_key, priority, hint in entries:
                    db.add(DocumentTypeField(
                        document_type_id=types[type_key], field_id=fields[field_key],
                        priority=priority, extraction_hint=hint,
                    ))
                    n += 1
            print(f"document_type_fields: {n} mappings")

            db.commit()
            print("\nseed_reference: ok")
            return 0
        except Exception as exc:
            db.rollback()
            print(f"seed_reference failed: {exc}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
