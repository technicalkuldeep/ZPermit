# ZPermit

Privacy-conscious AI spending authorization platform for the Free Society Hackathon.
Milestone 1 provides the FastAPI backend foundation only: configuration, health,
CORS, database sessions, and tests.

## Installation

Requires Python 3.11+ with pip and venv support. On Debian/Ubuntu, install the
matching `python3-venv` package if virtual environment creation fails.

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
cp .env.example .env
```

## Start locally

With the virtual environment activated, run from `backend/`:

```bash
uvicorn app.main:app --reload
```

- Health: http://127.0.0.1:8000/health
- Swagger UI: http://127.0.0.1:8000/docs
- OpenAPI schema: http://127.0.0.1:8000/openapi.json

`GET /health` returns `{"status":"ok","service":"zpermit"}`. This is a
liveness endpoint; it does not check database connectivity. Reload is intended
for local development; omit `--reload` for deployment.

## Configuration

Settings load from `backend/.env` and environment variables prefixed with
`ZPERMIT_`. Environment variables take precedence. Configuration is cached for
the process lifetime; restart after changes. Keep secrets out of version control.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ZPERMIT_DATABASE_URL` | `sqlite:///./zpermit.db` | SQLAlchemy connection URL |
| `ZPERMIT_CORS_ORIGINS` | `[]` | JSON array of explicit HTTP(S) origins |

The example environment file allows localhost ports 3000 and 5173. Origins must
include the scheme and optional port, without a trailing slash or path. Wildcards
are rejected. Browser credentials are disabled; allowed methods currently include
only GET. Expand this policy explicitly when adding routes.

SQLite uses Python's built-in driver; no database server is required. Relative
SQLite paths resolve from the working directory, so start from `backend/`.
The engine is created lazily, and no tables or database files are created at
startup. Future routes can inject `app.core.database.get_db` with FastAPI's
`Depends`. Sessions close after use and roll back on errors; write operations
must commit explicitly. Models should inherit from `app.core.database.Base`.
Schema migrations and application models belong to later milestones.

## Tests

From `backend/`, with development dependencies installed:

```bash
python -m pytest -q
```

Tests cover health, Swagger/OpenAPI, CORS allow/deny behavior, configuration
defaults and overrides, invalid configuration, and SQLite commit/rollback.
Database tests use temporary files and do not touch the local development database.

## Layout

```text
backend/
  app/
    main.py
    api/        # HTTP routes
    core/       # Settings and database infrastructure
    models/     # Future SQLAlchemy models
    schemas/    # Pydantic API schemas
    services/   # Future business logic
  tests/
  .env.example
  pyproject.toml
```

No payment, Zcash, Bitrefill, AI agent, or frontend implementation is included.
