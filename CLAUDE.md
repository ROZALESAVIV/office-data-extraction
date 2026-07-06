# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A SaaS tool for Israeli law firms. Narrow scope:
1. Receive case documents (PDF/DOCX)
2. Extract a fixed set of data fields using the Claude API
3. Let a lawyer review and validate the extracted data
4. Submit confirmed data to Odcanit (existing legal CRM — www.od.co.il)

This is **not** a case management system. Case lifecycle, billing, deadlines, and court dates remain Odcanit's job.

## Stack

| Layer | Technology |
|---|---|
| Frontend | React + TypeScript (Vite) — not yet started |
| Backend | FastAPI (Python) |
| ORM | SQLAlchemy 2.0 + Alembic |
| Database | PostgreSQL (Supabase) — multi-tenant via Row-Level Security (RLS) |
| Extraction | Claude API — vision for scanned PDFs, plain text for extractable docs |
| File storage | Cloudflare R2 (S3-compatible) — **deferred, not the current priority** |
| Background jobs | FastAPI `BackgroundTasks` for now; seam designed to swap to Celery + Redis later |
| Auth | JWT (python-jose) + bcrypt |

## Actual folder structure

```
backend/
  alembic/
    versions/           # migration files — authoritative source of truth for schema
  models/
    models.py           # SQLAlchemy ORM — all 9 tables (NOT inside app/)
  app/
    main.py             # FastAPI app, includes routers
    schemas.py          # Pydantic request/response models
    deps.py             # get_current_user, get_current_user_with_tenant
    routers/
      auth.py           # POST /auth/login, GET /auth/me       ✅ done
      cases.py          # full CRUD for cases                  ✅ done
      documents.py      # document records (no file upload yet) ← next
    services/
      extraction.py     # Claude API calls → case_field_values  ← next
      storage.py        # R2 upload/download — deferred
      odcanit.py        # Odcanit API client
  config.py             # pydantic-settings: DB URL, JWT, Claude key
  database.py           # engine, SessionLocal, get_db, set_tenant
  seed.py               # dev: insert test tenant + user (run once)
  requirements.txt
  alembic.ini
  .env                  # never commit — see .env.example
```

## Development commands

```bash
# Backend (from backend/)
py -3 -m uvicorn app.main:app --reload
alembic upgrade head
alembic revision --autogenerate -m "<description>"
py -3 seed.py          # insert test tenant + user (run once after migrations)

# Frontend — not started yet
# npm run dev  (from frontend/)
```

## Data flow

1. **Intake** — a `cases` row is created (`status='intake'`), `documents` rows inserted (file upload deferred — `storage_path` holds a placeholder for now).
2. **Extraction** — a `BackgroundTask` runs `services/extraction.py` per document. Uses Claude vision API for scanned PDFs, plain text otherwise. Results write `case_field_values` rows: `extracted_value` is written once and frozen; `value` starts as a copy.
3. **Review** — lawyer sees the review UI, confirms/edits each field. Edits write to `.value` and `.status` only — `extracted_value` is never touched again.
4. **Submission** — `services/odcanit.py` posts confirmed field values to Odcanit; result logged in `odcanit_submissions`.

## Database schema

Full schema: `backend/schema.sql` — read it before writing any models or migrations.

> **Note:** `schema.sql` is missing the `password_hash` column on `users` (added in migration `e7e6e9c765ef`). Treat the **migration files** as the authoritative source of truth, not `schema.sql`.

### Architectural constraints — never change these silently

**Multi-tenancy (RLS)**
- Shared tables + `tenant_id` + Postgres Row-Level Security. NOT schema-per-tenant.
- Every tenant-scoped query must run inside a transaction where `SET LOCAL app.current_tenant_id = '<uuid>'` has already executed.
- FastAPI enforces this in `deps.get_current_user_with_tenant()` via `database.set_tenant()`.
- `users` has no RLS policy — login must look up by email before any tenant context exists.

**`case_fields` vs `case_field_values`**
- `case_fields` is a global template (not per-tenant, not per-case). Lists every data point the system knows how to extract.
- `case_field_values` holds the per-case answers — one row per field per case.
- Never collapse into a single table or a JSONB blob; the review UI needs per-field status, source document, and confidence score.

**Two-column value pattern**
- `case_field_values.extracted_value` = frozen AI output (written once, never overwritten)
- `case_field_values.value` = current value (what the lawyer confirmed or edited)
- Never write to `extracted_value` when a lawyer edits a field.

**Other constraints**
- Status columns: `TEXT + CHECK constraint`, not Postgres ENUM types — easier to evolve.
- Soft delete: `cases` and `documents` use `deleted_at`. Never hard-DELETE these rows.
- `documents.file_format` (`pdf`/`docx`) and `documents.text_extractable` (bool) are independent columns — do not merge.

## Background extraction jobs

Extraction is triggered as a `BackgroundTasks` job from the documents endpoint. The seam is deliberate — swap to Celery later by replacing `background_tasks.add_task(...)` with a Celery `.delay()` call; the service itself stays unchanged.

```python
@router.post("/cases/{case_id}/documents")
def create_document(..., background_tasks: BackgroundTasks):
    doc = create_document_row(...)
    background_tasks.add_task(extraction.run, doc.id)
    return doc
```

## File storage (deferred)

R2 is the chosen provider (S3-compatible, cheap, no egress fees) but **not being built yet**. `documents.storage_path` will store the R2 object key (`{tenant_id}/{case_id}/{filename}.pdf`) when this is implemented. Don't add R2 code until the decision is made to unblock it.

## Current status

| Area | Status |
|---|---|
| Database schema + RLS | ✅ Done — `schema.sql` + 2 Alembic migrations |
| SQLAlchemy ORM models | ✅ Done — `backend/models/models.py` |
| Alembic setup | ✅ Done |
| Auth (login + JWT + `/me`) | ✅ Done — `app/routers/auth.py` |
| Bug fixes (CORS, timing attack, config style, timestamps) | ✅ Done |
| Cases API (full CRUD, soft delete, RLS) | ✅ Done — `app/routers/cases.py` — all 10 tests passing |
| Documents API (metadata only, no file upload) | 🔲 Next |
| Extraction service (Claude API) | 🔲 Next after documents |
| File storage (Cloudflare R2) | ⏸ Deferred |
| Odcanit submission service | 🔲 Planned |
| Frontend (React + Vite) | 🔲 Not started |

## Cases API — endpoints built

| Method | Path | Description |
|---|---|---|
| POST | `/cases` | Create case (status=intake, tenant from JWT) |
| GET | `/cases` | List all non-deleted cases for the tenant |
| GET | `/cases/{id}` | Get one case |
| PATCH | `/cases/{id}` | Update status or subject (validates status values) |
| DELETE | `/cases/{id}` | Soft delete (sets deleted_at) |
