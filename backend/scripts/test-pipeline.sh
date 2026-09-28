#!/bin/sh
set -e

echo "=== Step 1: Create test database ==="
PGPASSWORD=postgres psql -h "${PGHOST:-db}" -U postgres -d postgres -c "DROP DATABASE IF EXISTS dogfood_test;"
PGPASSWORD=postgres psql -h "${PGHOST:-db}" -U postgres -d postgres -c "CREATE DATABASE dogfood_test;"

echo "=== Step 2: Run test suite against PostgreSQL ==="
python -m pytest tests/ -v --tb=short

echo "=== Step 3: Reset dogfood database for migration ==="
PGPASSWORD=postgres psql -h "${PGHOST:-db}" -U postgres -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='dogfood' AND pid <> pg_backend_pid();"
PGPASSWORD=postgres psql -h "${PGHOST:-db}" -U postgres -d postgres -c "DROP DATABASE IF EXISTS dogfood;"
PGPASSWORD=postgres psql -h "${PGHOST:-db}" -U postgres -d postgres -c "CREATE DATABASE dogfood;"

echo "=== Step 4: Verify committed migrations match the models (no regeneration) ==="
python -m alembic upgrade head
python -m alembic check

echo "=== Step 5: (migrations already applied) ==="

echo "=== Step 6: Seed the database ==="
python -m scripts.seed

echo "=== Step 7: Start API and verify health ==="
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 &
API_PID=$!
sleep 3

echo "Health check:"
python -c "import httpx; r = httpx.get('http://localhost:8000/health'); print(r.json()); assert r.status_code == 200"

echo "Events list:"
python -c "import httpx; r = httpx.get('http://localhost:8000/events'); print(f'Status: {r.status_code}, Count: {len(r.json())}'); assert r.status_code == 200"

echo "=== ALL PIPELINE STAGES PASSED ==="
kill $API_PID 2>/dev/null
