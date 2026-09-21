# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start here

| File | What it holds |
|---|---|
| **CLAUDE.md** (this file) | The code: structure, commands, technical constraints |
| **DOMAIN.md** | The business: insurance subrogation, the two case types, which document to believe, the deadline rule. None of it is derivable from the code. |
| **DECISIONS.md** | Every architectural decision with its reasoning and the alternative that was rejected. Read before changing anything that looks odd. |

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
| Extraction | Claude API (`claude-opus-5`) — PDF document blocks, model does its own OCR |
| File storage | Supabase Storage (`app/services/storage.py`) |
| Background jobs | FastAPI `BackgroundTasks` for now; seam designed to swap to Celery + Redis later |
| Auth | JWT (python-jose) + bcrypt |
| Tests | pytest against a real PostgreSQL (never SQLite) |
| Lint | ruff (`ruff check app alembic scripts tests`) |

## Actual folder structure

Everything importable lives under the `app` package, so there is a single import
root and the code runs from any working directory.

```
backend/
  app/
    main.py             # FastAPI app, CORS from config, /health
    deps.py             # tenant context + role dependencies
    audit.py            # audit_log helper — call from every mutation
    core/
      config.py         # pydantic-settings
      database.py       # engines, TenantSession, get_db, set_tenant, admin_session
    models/
      models.py         # SQLAlchemy ORM — all 9 tables
    schemas/            # Pydantic models, split by topic; re-exported from __init__
      auth.py  cases.py  senders.py
    routers/
      auth.py           # POST /auth/login, GET /auth/me       done
      cases.py          # full CRUD for cases                  done
      senders.py        # list/create senders                  done
      documents.py      # upload, list, signed URL, reclassify  done
    reference/          # product configuration, loaded by scripts/seed_reference
      document_types.py # 41 types; is_extractable decides what reaches the model
      case_fields.py    # 42 fields + which document type supplies each
      deadlines.py      # the 45/60-day defence filing rule
    services/
      files.py          # format sniffing, Hebrew normalization, PDF inspection
      referral_email.py # parses the insurer's email - 7 fields, no model
      storage.py        # Supabase Storage; keys are UUIDs only
      llm.py            # <- planned: the only module touching the Claude API
      extraction.py     # <- planned: Claude API -> field_candidates
      odcanit.py        # <- planned: Odcanit client (not a REST API, see below)
  alembic/versions/     # migrations — authoritative source of truth for schema
  scripts/
    seed.py             # dev tenant + user (idempotent, admin connection)
  tests/
    conftest.py         # forces a local throwaway DB; two DB roles
    test_rls.py         # tenant isolation proof — the gate for everything
    test_auth.py  test_cases.py  test_senders.py
    test_files.py  test_documents.py  test_deadlines.py
    test_schema_invariants.py
  pyproject.toml        # pytest + ruff config
  requirements.txt
  alembic.ini
  .env                  # never commit — see .env.example
```

Removed deliberately: `schema.sql` (a second source of truth that had already
drifted from the migrations and misled the docs — regenerate with
`pg_dump --schema-only` when a readable snapshot is wanted) and the root
`test_storage.py` smoke script (superseded by the test suite).

## Development commands

```bash
# Backend (from backend/)
python -m uvicorn app.main:app --reload
alembic upgrade head
alembic revision --autogenerate -m "<description>"
python -m scripts.seed            # dev tenant + user
python -m scripts.seed_reference  # document types, fields, mapping

# Tests — need a real PostgreSQL. A throwaway one:
podman run -d --name ode-test-pg -e POSTGRES_PASSWORD=testpw \
  -e POSTGRES_DB=ode_test -p 55432:5432 docker.io/library/postgres:16-alpine
pytest                  # conftest forces the local DB; it never uses your .env

# Frontend — not started yet
```

## Data flow

1. **Intake** — a `cases` row is created (`status='intake'`), `documents` rows inserted.
2. **Classification + extraction** — a `BackgroundTask` runs `services/extraction.py` per document: classify the document type, then extract only the fields mapped to that type via `document_type_fields`. Results write `field_candidates` rows.
3. **Resolution** — candidates are resolved into one `case_field_values` row per field, by `priority` then confidence. Disagreements set `has_conflict`.
4. **Review** — lawyer confirms/edits each field. Edits write `.value` and `.status`.
5. **Submission** — `services/odcanit.py` submits confirmed values; result logged in `odcanit_submissions`.

## Database schema

The **migration files are the authoritative source of truth** for the schema. There is deliberately no checked-in `schema.sql`: it drifted from the migrations and misled the documentation. For a readable snapshot, run `pg_dump --schema-only`.

### Architectural constraints — never change these silently

**Multi-tenancy (RLS) — read this before touching anything database-related**

- Shared tables + `tenant_id` + Postgres Row-Level Security. NOT schema-per-tenant.
- **The application must connect as a dedicated role that is not the table owner and has neither `SUPERUSER` nor `BYPASSRLS`.** This is *the* load-bearing control. `FORCE ROW LEVEL SECURITY` alone does **not** help — it closes the plain-owner case but has no effect on a superuser or a `BYPASSRLS` role. Supabase's default `postgres` role is a superuser, so using it for `DATABASE_URL` disables tenant isolation completely and silently. Verified experimentally: with identical policies, `postgres` saw every tenant's rows while the dedicated role saw only its own.
- Two connection URLs: `DATABASE_URL` (app role, RLS applies) and `DATABASE_ADMIN_URL` (owner; Alembic and the startup sweeper only).
- Every tenant-scoped query runs inside a transaction where `app.current_tenant_id` is set. `database.TenantSession` re-applies it on `after_begin`, so it **survives `commit()`** — a plain `SET LOCAL` does not, and the routers commit-then-refresh.
- **Also filter by `tenant_id` explicitly in every query.** RLS is the enforcement; the explicit filter is defence in depth so a single policy mistake is not a disclosure.
- Foreign-key checks bypass RLS. Any `*_id` accepted from a request body must be validated against the caller's tenant (see `cases._validate_sender`).
- `users` has no RLS policy — login must look up by email before any tenant context exists. This is the **only** exemption, asserted by `test_rls_exemptions_are_only_the_documented_ones`.
- The app role has no `DELETE` grant. `cases` and `documents` are soft-deleted via `deleted_at`.

**`case_fields` vs `case_field_values` vs `field_candidates`**

- `case_fields` — global template. Every data point the system knows how to extract.
- `document_type_fields` — which fields to look for in which document type, with `priority` (**lower = more authoritative**) and an optional `extraction_hint`.
- `field_candidates` — one row per (document, field): what that document said, with confidence, page, and a verbatim snippet.
- `case_field_values` — the resolved answer, one row per field per case.
- Never collapse into a single table or a JSONB blob; the review UI needs per-field status, source document, and confidence.

**Two-column value pattern**

- `case_field_values.extracted_value` = the AI's output; `value` = current value.
- `extracted_value` may be updated **only** while `status='pending_review' AND reviewed_at IS NULL`, so a better source document arriving later can still correct it. Once a lawyer confirms, edits or rejects, it is frozen permanently — enforced by the `trg_freeze_extracted_value` database trigger, not by router discipline.
- Never write to `extracted_value` when a lawyer edits a field.

**Other constraints**
- Status columns: `TEXT + CHECK constraint`, not Postgres ENUM types — easier to evolve.
- `documents.file_format` (`pdf`/`docx`) and `documents.text_extractable` (bool) are independent columns — do not merge.
- Locally extracted PDF text is **not** input to the model. Hebrew text layers frequently come back in visual (reversed) order. It is used only to verify that a returned snippet really appears on the claimed page.
- Every mutating endpoint writes an `audit_log` row via `app.audit.record`.

## Odcanit integration — not a REST API

Odcanit exposes **direct Microsoft SQL Server access**: Views for reading, Stored Procedures for writing. There is no HTTP API. Consequences:

- The client is `pyodbc`/`pymssql`, not `httpx`.
- The database most likely lives on a server inside the firm's own network, unreachable from a cloud backend. The connectivity model is **unresolved** — build behind an interface with a mock and a file-export fallback that always works.
- Opening a case is **two** stored procedures (entity, then case) — needs transactional behaviour.
- Per-tenant SQL Server credentials must be stored encrypted at rest.
- Odcanit states there is no backwards-compatibility guarantee. Expect breakage; add a contract test.

## Background extraction jobs

Triggered as a `BackgroundTasks` job from the documents endpoint. The seam is deliberate — swap to Celery later by replacing `background_tasks.add_task(...)` with `.delay()`; the service itself stays unchanged.

`BackgroundTasks` swallows exceptions silently, so `extraction.run` must never propagate one; it catches at the top and marks the document failed. Documents are leased via `processing_started_at` and recovered at startup by a sweeper using `admin_session()` — the only sanctioned RLS bypass in the codebase.

## Current status

| Area | Status |
|---|---|
| Database schema + RLS | ✅ Done — 5 Alembic migrations |
| SQLAlchemy ORM models | ✅ Done — `backend/models/models.py` |
| Auth (login + JWT + `/me`) | ✅ Done |
| Cases API (full CRUD, soft delete) | ✅ Done |
| Senders API | ✅ Done |
| Tenant isolation hardening + test suite | ✅ Done — 128 tests passing |
| Role-based permissions (`owner`/`lawyer`/`staff`) | ✅ Done |
| Audit logging | ✅ Done |
| Reference data (41 document types, 42 fields, 66 mappings) | ✅ Done — derived from 6 real case files |
| Extraction schema (`document_type_fields`, `field_candidates`) | ✅ Done |
| Documents API + upload | ✅ Done — content sniffing, dedupe, soft delete |
| Referral email parser | ✅ Done — 7 fields, no model, 6/6 samples |
| Defence deadline rule | ✅ Done — `app/reference/deadlines.py` |
| Extraction service (Claude API) | 🔲 Next |
| Review API | 🔲 Planned |
| Odcanit submission service | 🔲 Planned — connectivity model unresolved |
| Frontend (React + Vite, RTL) | 🔲 Not started |

## API endpoints built

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/login` | OAuth2 password form → JWT |
| GET | `/auth/me` | Current user |
| POST | `/cases` | Create (status=intake, readable `YYYY-NNNN` number). Write role. |
| GET | `/cases` | List non-deleted cases for the tenant |
| GET | `/cases/{id}` | Get one; cross-tenant → 404 |
| PATCH | `/cases/{id}` | Update status or subject. Write role. |
| DELETE | `/cases/{id}` | Soft delete. Write role. |
| GET | `/senders` | List active senders (never exposes `odcanit_prefix`) |
| POST | `/senders` | Create. Owner only. Duplicate name → 409. |
| POST | `/cases/{id}/documents` | Multipart upload. Any tenant member. |
| GET | `/cases/{id}/documents` | Documents of a case |
| GET | `/documents/{id}` | One document |
| GET | `/documents/{id}/url` | Short-lived signed URL for the viewer |
| PATCH | `/documents/{id}` | Override the classification. Write role. |
| DELETE | `/documents/{id}` | Soft delete. Write role. |
| GET | `/document-types` | The catalogue, for re-classification |
| GET | `/health` | Liveness |
