# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Start here

| File | What it holds |
|---|---|
| **CLAUDE.md** (this file) | The code: structure, commands, technical constraints |
| **DOMAIN.md** | The business: insurance subrogation, the two case types, which document to believe, the deadline rule. None of it is derivable from the code. |
| **DECISIONS.md** | Every architectural decision with its reasoning and the alternative that was rejected. Read before changing anything that looks odd. |
| **QUESTIONS.md** | What only the firm can answer. Every assumption the code is currently running on, named so it is not mistaken for a fact. Add to it rather than guessing twice. |

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
| Frontend | React + TypeScript (Vite), Hebrew/RTL — intake + review screens built |
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
      auth.py  cases.py  senders.py  documents.py  review.py
    routers/
      auth.py           # POST /auth/login, GET /auth/me       done
      cases.py          # full CRUD for cases                  done
      senders.py        # list/create senders                  done
      documents.py      # upload, list, signed URL, reclassify  done
      review.py         # the review screen: read, decide, readiness  done
    reference/          # product configuration, loaded by scripts/seed_reference
      document_types.py # 39 types, 17 extractable; is_extractable decides what reaches the model
      case_fields.py    # 45 fields + which document type supplies each
      case_types.py     # the two case types; matched exactly, never as a substring
      deadlines.py      # the 45/60-day defence filing rule
      review.py         # attention thresholds + the per-case-type required set
    services/
      files.py          # format sniffing, Hebrew normalization, PDF inspection
      referral_email.py # parses the insurer's email - 7 fields, no model
      storage.py        # Supabase Storage; keys are UUIDs only
      llm.py            # the ONLY module touching the Claude API; swap models here
      extraction.py     # classify -> navigate -> extract -> resolve
      review.py         # screen assembly + the readiness rule (reused by submit)
      odcanit.py        # <- planned: Odcanit client (not a REST API, see below)
  alembic/versions/     # migrations — authoritative source of truth for schema
frontend/               # React + TypeScript (Vite). Hebrew, RTL. See frontend/README.md
  src/
    api/                # types.ts mirrors the Pydantic schemas; client.ts is the only caller
    lib/hebrew.ts       # every string the lawyer reads, in one file
    routes/             # UploadPage (intake), ReviewPage (the product)
    components/         # FieldRow, ConflictDialog, ReadinessPanel, DocumentViewer
  scripts/
    seed.py             # dev tenant + user (idempotent, admin connection)
  tests/
    conftest.py         # forces a local throwaway DB; two DB roles
    test_rls.py         # tenant isolation proof — the gate for everything
    test_auth.py  test_cases.py  test_senders.py
    test_files.py  test_documents.py  test_deadlines.py  test_review.py
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

# Frontend (from frontend/) — needs the API on port 8000
npm install
npm run dev        # http://localhost:5173, proxies /api to the backend
npm run build      # type-check + production bundle
```

**Never point the dev backend at the firm's real Supabase project while
developing.** Use a local throwaway database:

```bash
psql -h localhost -p 55432 -U postgres -c "CREATE DATABASE ode_dev"
export DATABASE_ADMIN_URL="postgresql://postgres:testpw@localhost:55432/ode_dev"
export DATABASE_URL="postgresql://ode_app:ode_app_test_pw@localhost:55432/ode_dev"
export APP_DB_ROLE=ode_app APP_DB_PASSWORD=ode_app_test_pw JWT_SECRET=dev-only
alembic upgrade head && python -m scripts.seed && python -m scripts.seed_reference
python -m uvicorn app.main:app --port 8000
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

**The review stage**

- `case_field_values.updated_at` is an optimistic-locking token. Every
  single-field mutation sends `expected_updated_at` and gets 409 on a mismatch.
  Omitting it asserts *no row exists yet* — it is not a way to opt out.
- The token is maintained by the `trg_touch_case_field_value` trigger
  (`clock_timestamp()`, not `now()`), not by router discipline.
- A **read never changes the case status.** `ready_for_review -> in_review` is
  set by the first *mutation*. `in_review` is terminal for
  `recompute_case_status`, so a glance must not freeze a case.
- Required-ness is per case type: `case_fields.is_required` is the shared list,
  and `app/reference/review.DEFENCE_ONLY_REQUIRED` adds the court fields when
  `case_type` is `הגנה`. In a claim case those fields are correctly empty.
- `readiness` is a convenience. The submission endpoint must recompute
  `services/review.readiness()` server-side and refuse with the same payload.

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
| Tenant isolation hardening + test suite | ✅ Done — 158 tests passing |
| Role-based permissions (`owner`/`lawyer`/`staff`) | ✅ Done |
| Audit logging | ✅ Done |
| Reference data (39 document types, 45 fields, 83 mappings) | ✅ Done — derived from 6 real case files |
| Extraction schema (`document_type_fields`, `field_candidates`) | ✅ Done |
| Documents API + upload | ✅ Done — content sniffing, dedupe, soft delete |
| Referral email parser | ✅ Done — 7 fields, no model, 6/6 samples |
| Defence deadline rule | ✅ Done — `app/reference/deadlines.py` |
| Extraction service (Claude API) | ✅ Done — classify, navigate, extract, resolve |
| Referral email wired into the pipeline | ✅ Done — 7 fields, no model call |
| Startup recovery for stalled jobs | ✅ Done |
| Review API | ✅ Done — fields, candidates, confirm/edit/reject, bulk, readiness |
| Odcanit submission service | 🔲 **Next** — connectivity model unresolved |
| `case_type` closed to two values | ✅ Done — API, read path and a blocker for legacy data |
| Frontend — intake + review screens | ✅ Done — React + Vite, Hebrew, RTL |
| Frontend — submission screen | 🔲 Blocked on the Odcanit contract |

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
| GET | `/cases/{id}/fields` | The whole review screen, one call. Any tenant member. |
| GET | `/cases/{id}/fields/{fid}/candidates` | What each document said, resolver order |
| POST | `/cases/{id}/fields/{fid}/confirm` | Accept the value. Write role. Empty → 422. |
| PATCH | `/cases/{id}/fields/{fid}` | Lawyer's own value; upserts. Write role. |
| POST | `/cases/{id}/fields/{fid}/reject` | Wrong, no replacement. Write role. |
| POST | `/cases/{id}/fields/{fid}/select-candidate` | Resolve a conflict by picking a document |
| POST | `/cases/{id}/fields/bulk-confirm` | High-confidence sweep; returns every skip reason |
| GET | `/cases/{id}/readiness` | Blockers and warnings for submission |
| GET | `/health` | Liveness |
