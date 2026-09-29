#!/usr/bin/env bash
# Run the whole thing locally: API on 8000, screens on 5173.
#
# Deliberately points at a LOCAL throwaway database, never at backend/.env —
# that file points at the firm's live Supabase project, and developing against
# it would mean editing real case files.
set -euo pipefail
cd "$(dirname "$0")"

export DATABASE_ADMIN_URL="postgresql://postgres:testpw@localhost:55432/ode_dev"
export DATABASE_URL="postgresql://ode_app:ode_app_test_pw@localhost:55432/ode_dev"
export APP_DB_ROLE="ode_app"
export APP_DB_PASSWORD="ode_app_test_pw"
export JWT_SECRET="dev-only-not-a-real-secret"
export SUPABASE_URL="" SUPABASE_SERVICE_KEY="" ANTHROPIC_API_KEY=""
export CORS_ORIGINS="http://localhost:5173"

if ! pg_isready -h localhost -p 55432 -q; then
  echo "Postgres is not up on 55432. Start it with:"
  echo "  podman start ode-test-pg"
  exit 1
fi

cleanup() { kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

( cd backend && .venv/bin/python -m uvicorn app.main:app --port 8000 --reload ) &
( cd frontend && npm run dev ) &

echo
echo "  API      http://localhost:8000/docs"
echo "  Screens  http://localhost:5173"
echo "  Login    admin@testfirm.com / secret123"
echo
wait
