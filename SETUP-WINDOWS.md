# Setting up this project on Windows

Instructions for an AI coding agent (or a person) setting up a fresh Windows
machine to develop and run this project. Work through the steps **in order**.
Every step ends with a check; do not continue past a check that fails — fix
it, or stop and report exactly what failed.

The user does not read code. Report progress as "step N done / failed and
why", not as command output.

---

## Ground rules — read before running anything

- **Shell:** PowerShell (not cmd, not Git Bash). All commands below are
  PowerShell.
- **Never point the development database at Supabase.** Development and tests
  use a local PostgreSQL. The Supabase project holds real data; the app's
  tenant isolation depends on a specific role setup there (see CLAUDE.md).
- **Never commit** `backend/.env` or anything in `samples/` (real client
  documents). Both are already in `.gitignore`; keep it that way.
- After any `winget install`, **close and reopen PowerShell** so the new
  programs are on `PATH`.
- Read `CLAUDE.md` after setup for how the code is organised. Its command
  examples are written for Linux (`export`, `podman`); this file is the
  Windows equivalent.

---

## Step 0 — Things that are NOT in git (the user brings these)

Git only carries the code. Three things must be carried over by hand from the
old machine:

| What | Where it goes | Why it is not in git |
|---|---|---|
| `ANTHROPIC_API_KEY` | `backend\.env` | Secret. Needed for real extraction. |
| `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` | `backend\.env` | Secret. Needed to upload documents (file storage). |
| The `samples\` folder | repo root | Real client case files. Transfer securely — not by email, not via a public cloud link. |

The tests need **none** of these. If the user doesn't have them yet, do every
step anyway — only uploading documents and real extraction will be missing.

**Do not copy the old `DATABASE_URL` / `DATABASE_ADMIN_URL` lines.** On the old
machine they pointed at Supabase. Step 6 sets them to the local database.

---

## Step 1 — Install the tools

Run each line. `winget` comes with Windows 10/11. If a package is already
installed, winget says so and that is fine.

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.14 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id PostgreSQL.PostgreSQL.16 -e --override "--mode unattended --unattendedmodeui none --superpassword testpw --serverport 55432"
```

About the PostgreSQL line: it installs PostgreSQL 16 as a **Windows service
that starts automatically with the computer**. On the old machine Postgres ran
in a container that had to be started by hand every time, which caused
problems; on Windows that doesn't happen. The password `testpw` and port
`55432` match what the test suite expects (`backend\tests\conftest.py`), so no
config needs changing. This is a local throwaway database; that password is
deliberately not a secret.

**Close and reopen PowerShell**, then check:

```powershell
git --version        # any version
python --version     # Python 3.14.x
node --version       # v22.x or newer
npm --version
```

---

## Step 2 — One-time PowerShell and Python settings

```powershell
# Allow the venv activation script to run (current user only).
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned -Force

# Make Python use UTF-8 everywhere. Without this, Hebrew text in file names
# and in output can crash scripts with UnicodeEncodeError on Windows.
setx PYTHONUTF8 1

# Put the PostgreSQL tools (psql) on PATH.
$pgBin = "C:\Program Files\PostgreSQL\16\bin"
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$pgBin*") {
    [Environment]::SetEnvironmentVariable("Path", "$userPath;$pgBin", "User")
}
```

**Close and reopen PowerShell**, then check:

```powershell
$env:PYTHONUTF8                                # 1
psql --version                                 # psql (PostgreSQL) 16.x
Get-Service postgresql*                        # Status: Running
```

If the service isn't `Running`: `Start-Service postgresql-x64-16`, and set it
to start with Windows: `Set-Service postgresql-x64-16 -StartupType Automatic`.

---

## Step 3 — Get the code

Pick a folder **without spaces or Hebrew in its path** (for example
`C:\dev`). Some tools still break on such paths.

```powershell
mkdir C:\dev -Force
cd C:\dev
git clone https://github.com/ROZALESAVIV/office-data-extraction.git
cd office-data-extraction
```

If the user has the `samples\` folder, copy it to
`C:\dev\office-data-extraction\samples\` now.

Check: `git status` shows `On branch main` and a clean tree.

---

## Step 4 — Create the two local databases

```powershell
$env:PGPASSWORD = "testpw"
psql -h localhost -p 55432 -U postgres -c "CREATE DATABASE ode_test"
psql -h localhost -p 55432 -U postgres -c "CREATE DATABASE ode_dev"
```

`ode_test` is wiped and rebuilt by every test run. `ode_dev` is the one the
running app uses. Keep them separate.

Check:

```powershell
psql -h localhost -p 55432 -U postgres -c "\l" | Select-String ode_
```

Both `ode_test` and `ode_dev` should be listed.

---

## Step 5 — Backend: Python environment and packages

```powershell
cd C:\dev\office-data-extraction\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install ruff
```

From now on, every backend command assumes the venv is **active** (the prompt
starts with `(.venv)`) and the current folder is `backend`. In a new terminal,
reactivate it:

```powershell
cd C:\dev\office-data-extraction\backend
.\.venv\Scripts\Activate.ps1
```

Check:

```powershell
python -c "import fastapi, sqlalchemy, psycopg2, anthropic, pypdf; print('ok')"
```

**If `pip install` fails on `psycopg2-binary`** with a build error mentioning
`pg_config` or a C compiler: there is no prebuilt package for this Python
version yet. Remove the venv, install Python 3.13
(`winget install --id Python.Python.3.13 -e`), recreate the venv with
`py -3.13 -m venv .venv`, and repeat this step.

---

## Step 6 — Backend: the `.env` file

Create `backend\.env` with the content below. The application reads it from
the **current folder**, which is why backend commands always run from
`backend\`.

```ini
# Local database — never Supabase in development.
DATABASE_URL=postgresql://ode_app:ode_app_test_pw@localhost:55432/ode_dev
DATABASE_ADMIN_URL=postgresql://postgres:testpw@localhost:55432/ode_dev
APP_DB_ROLE=ode_app
APP_DB_PASSWORD=ode_app_test_pw

JWT_SECRET=dev-only-not-a-secret
JWT_ALGORITHM=HS256
JWT_EXPIRE_MINUTES=480

CORS_ORIGINS=http://localhost:5173

# Filled in by the user from the old machine (Step 0). Leave empty if missing.
ANTHROPIC_API_KEY=
SUPABASE_URL=
SUPABASE_SERVICE_KEY=
SUPABASE_BUCKET=case-documents
```

**Why `ode_app_test_pw` and not a password of your choice:** `ode_app` is one
database role shared by `ode_test` and `ode_dev` (roles belong to the whole
Postgres server, not to one database). Every test run resets its password to
`ode_app_test_pw`. A different password here would work until the first test
run, and then the app would fail with `password authentication failed for user
"ode_app"`.

**Do not use the `postgres` role in `DATABASE_URL`.** It is a superuser and
silently disables tenant isolation (CLAUDE.md, "Multi-tenancy").

The user pastes their three secrets into the empty lines. Never print the
secret values back to the user or into logs.

---

## Step 7 — Run the test suite

```powershell
pytest
```

Expected: everything **passes**, with **no** skips.

- `skipped: No test PostgreSQL at ...`: Postgres isn't reachable. Re-check
  Step 2 (service running) and Step 4 (`ode_test` exists).
- Anything else failing: stop and report the failing test names and the
  first error. Do **not** change code to make a test pass.

Lint:

```powershell
ruff check app alembic scripts tests
```

Expected: `All checks passed!`

---

## Step 8 — Set up the development database

```powershell
alembic upgrade head
python -m scripts.seed
python -m scripts.seed_reference
```

`seed` creates a development firm and user. `seed_reference` loads the
document types and fields. Both are safe to run again.

Check: `seed` printed a tenant id and no error.

---

## Step 9 — Run the backend

```powershell
python -m uvicorn app.main:app --reload --port 8000
```

Leave this terminal running. In a **second** terminal:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected: `status : ok`.

---

## Step 10 — Run the frontend

In a **third** terminal:

```powershell
cd C:\dev\office-data-extraction\frontend
npm ci
npm run dev
```

`npm ci` installs the exact versions from `package-lock.json`; use it rather
than `npm install` so nothing changes unexpectedly.

Open http://localhost:5173 and log in:

```
email:     admin@testfirm.com
password:  secret123
```

(Local development user from `backend\scripts\seed.py`. Not a real account.)

Check: the case list loads. Creating a case works without the secrets.
Uploading documents needs the Supabase keys, and extraction needs the
Anthropic key (Step 0).

Also check that the frontend compiles cleanly:

```powershell
npm run build
```

---

## Every day after setup

PostgreSQL starts with Windows by itself, so there is nothing to start for it.
Two terminals:

```powershell
# Terminal 1 — backend
cd C:\dev\office-data-extraction\backend
.\.venv\Scripts\Activate.ps1
python -m uvicorn app.main:app --reload --port 8000
```

```powershell
# Terminal 2 — frontend
cd C:\dev\office-data-extraction\frontend
npm run dev
```

After pulling changes, with the venv active and from `backend\`:

| What changed | Run |
|---|---|
| A new file in `backend\alembic\versions\` (table structure) | `alembic upgrade head` |
| `backend\app\reference\` (document types, fields, priorities) | `python -m scripts.seed_reference` |
| `backend\requirements.txt` | `pip install -r requirements.txt` |
| `frontend\package-lock.json` | `npm ci` (in `frontend\`) |

When unsure, running all of them is safe — each one only applies what is
missing.

---

## How the database is managed (code-first)

The code is the single source of truth for the database. Nothing is ever
added to a database by hand.

- **Table structure** lives in the migrations (`backend\alembic\versions\`).
  `alembic upgrade head` brings any database up to date.
- **Reference data** — document types, fields, which document supplies which
  field and at what priority — lives in `backend\app\reference\`.
  `python -m scripts.seed_reference` loads it into a database.

To add or change a document type or a field:

1. Edit the list in `backend\app\reference\document_types.py` or
   `case_fields.py`.
2. Run `python -m scripts.seed_reference` against the **local** dev database
   and check it works.
3. Run `pytest`.
4. Commit and push. The other machine picks it up with the table above.
5. The shared Supabase database is updated by running the same script against
   it, deliberately and once — never as part of development. Don't do this
   unless the user explicitly asks.

Each machine has its own local database, so cases created on one machine
don't appear on another. That is expected.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Activate.ps1 cannot be loaded because running scripts is disabled` | Step 2's `Set-ExecutionPolicy` was skipped. |
| `password authentication failed for user "ode_app"` | `APP_DB_PASSWORD`/`DATABASE_URL` in `.env` don't use `ode_app_test_pw`. Fix `.env`, then `alembic upgrade head`. |
| `password authentication failed for user "postgres"` | The installer didn't take `testpw`. Reset it: open **SQL Shell (psql)** from the Start menu, log in with the password you did set, run `ALTER USER postgres PASSWORD 'testpw';`. |
| `connection refused` on port 55432 | The service isn't running (`Get-Service postgresql*`), or Postgres was installed on port 5432. If it's 5432, the easiest fix is to reinstall with the Step 1 command; otherwise set `TEST_DATABASE_ADMIN_URL` / `TEST_DATABASE_URL` and change the ports in `.env`. |
| `UnicodeEncodeError` / Hebrew shows as `???` | `PYTHONUTF8` isn't set in this terminal. Reopen PowerShell after Step 2. |
| `ModuleNotFoundError: No module named 'app'` | The command wasn't run from `backend\`, or the venv isn't active. |
| `Supabase storage is not configured` on upload | `SUPABASE_URL` / `SUPABASE_SERVICE_KEY` missing from `.env` (Step 0). |
| `ANTHROPIC_API_KEY is not configured` / documents end as failed | The Anthropic key is missing from `.env` (Step 0). |
| Port 8000 or 5173 already in use | Another copy is running. Close it, or `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess`. |
| Git warns `LF will be replaced by CRLF` | Harmless on Windows. Don't change line-ending settings mid-project. |
