# Office Data Extraction System

Extract structured data from Israeli legal case documents (Hebrew PDFs and Word
files), have a lawyer review it, and submit it to Odcanit.

## Goals

* Upload case documents (scanned PDF, text PDF, DOCX)
* Extract a fixed set of fields with the Claude API
* Let a lawyer review and confirm every value, with the source page and quote
* Submit the confirmed data to Odcanit

## Tech Stack

* Backend: FastAPI (Python), SQLAlchemy 2.0, Alembic
* Database: PostgreSQL (Supabase), multi-tenant via Row-Level Security
* Storage: Supabase Storage
* Extraction: Claude API
* Frontend: React + TypeScript (not started)

## Current stage

Backend foundations. Auth, cases, senders and tenant isolation are done and
covered by tests. Document upload, extraction, the review screen and the
frontend are not built yet.

See [CLAUDE.md](CLAUDE.md) for architecture, constraints and current status.

## Running

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env        # then fill it in — read the comments about DATABASE_URL
alembic upgrade head
python -m scripts.seed
python -m uvicorn app.main:app --reload
```

## Tests

The suite needs a real PostgreSQL — row-level security, triggers and advisory
locks do not exist in SQLite. It always uses a local throwaway database and
never reads your `.env`.

```bash
podman run -d --name ode-test-pg -e POSTGRES_PASSWORD=testpw \
  -e POSTGRES_DB=ode_test -p 55432:5432 docker.io/library/postgres:16-alpine
cd backend && pytest
```
