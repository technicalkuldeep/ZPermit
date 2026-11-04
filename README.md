# ZPermit

Privacy-conscious AI spending authorization platform for the Free Society Hackathon.
Milestones 1–2 provide a FastAPI backend and deterministic permit policy engine.
Authorization reserves a budget; **no payments or purchases are executed**.

## Installation and startup

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

Edit `backend/.env` to set two independently generated random credentials. For
example, run this command twice and copy each result to the corresponding
credential setting. Do not share, commit, or log these values:

```bash
python -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Initialize the SQLite schema, then start from `backend/`:

```bash
python -m app.core.init_db
uvicorn app.main:app --reload
```

- Health: http://127.0.0.1:8000/health
- Swagger UI and example input schemas: http://127.0.0.1:8000/docs
- OpenAPI: http://127.0.0.1:8000/openapi.json

`GET /health` returns `{"status":"ok","service":"zpermit"}`. It is a liveness
check independent of database connectivity and credentials. Reload is for local
development. Schema initialization is explicit and idempotent for fresh tables;
`create_all` is **not** a migration system for modifying existing tables.

## Development identity boundary

This is development authentication, **not production-secure identity**. The server
has exactly one configured owner identity and one configured agent identity.
Bearer credentials separate their capabilities; owner IDs supplied in request
bodies are rejected, never treated as authentication. Permit ownership comes from
server settings. The agent credential is bound to `ZPERMIT_DEV_AGENT_ID`; using a
different `agent_id` in a proposal returns 403. A permit for another agent cannot
authorize this agent's request.

Both credentials must be nonempty and distinct; otherwise every `/api` spending
route fails closed with 503. Missing/invalid credentials return 401; a valid
credential with the wrong role returns 403. Credentials are masked in settings
representations and are never intentionally logged. Use only locally on a trusted
machine. Before deployment, replace this scheme with real identity, credential
management, TLS, and appropriate abuse controls. CORS is not authentication.

| Routes | Credential and scope |
| --- | --- |
| `POST /api/permits` | Owner; creates a permit owned by the configured owner |
| `GET /api/permits` | Owner; lists only that owner's permits |
| `GET /api/permits/{id}` | Owner; permit and spending summary |
| `POST /api/permits/{id}/revoke` | Owner; revokes and cancels outstanding requests |
| `POST /api/purchase-requests` | Agent; submits and evaluates a proposal |
| `GET /api/purchase-requests/{id}` | Owning owner or submitting agent |
| `POST /api/purchase-requests/{id}/approve` | Owning owner; pending requests only |
| `POST /api/purchase-requests/{id}/reject` | Owning owner; pending requests only |
| `POST /api/purchase-requests/{id}/cancel` | Owning owner or submitting agent; pending/authorized only |

Other owners' records return 404. Internal fulfillment/failure methods have no
HTTP routes. An agent cannot approve, reject, revoke, or create permits.

## Configuration

Settings load from `backend/.env` and environment variables prefixed with
`ZPERMIT_`. Environment variables take precedence. Restart after changing settings.
Local environment files and database files are ignored by Git.

| Variable | Default | Purpose |
| --- | --- | --- |
| `ZPERMIT_DATABASE_URL` | `sqlite:///./zpermit.db` | Local SQLite connection URL |
| `ZPERMIT_CORS_ORIGINS` | `[]` | JSON array of explicit HTTP(S) origins |
| `ZPERMIT_DEV_OWNER_ID` | `development-owner` | Server-assigned development owner |
| `ZPERMIT_DEV_AGENT_ID` | `shopping-agent` | Identity bound to the agent credential |
| `ZPERMIT_DEV_OWNER_CREDENTIAL` | unset | Development owner bearer credential |
| `ZPERMIT_DEV_AGENT_CREDENTIAL` | unset | Separate development agent bearer credential |

SQLite uses Python's built-in driver. Relative database paths resolve from the
working directory, so run from `backend/`. The example CORS settings allow
localhost ports 3000 and 5173. Origins require a scheme and optional port with no
path or trailing slash. Wildcards are rejected. Browser credentials are disabled;
GET, POST and the Authorization header are explicitly allowed.

## Policy and accounting

All money is strict integer cents, bounded to one trillion cents per input to
avoid integer overflow; floats, numeric strings and booleans return 422. Only USD
permits are supported. A proposal in another currency or with a zero/negative
integer amount is persisted as denied. Malformed inputs return 422 without
creating a request. Fields such as `approved`, `authorized`, `fulfilled`, `spent`,
`state`, or `owner_id` are forbidden in submissions.

Merchant/category identifiers are stripped, lowercased and matched by exact
identifier. They accept ASCII letters, digits, dots, underscores and hyphens,
start with a letter/digit, and are at most 128 characters. Permit lists are
nonempty, deduplicated, normalized child tables with composite primary keys,
not comma-separated strings or substring filters. Product and external request
IDs are opaque, case-sensitive strings; they are not claims of verified prices
or catalog provenance. No merchant integration exists in this milestone.

Policy checks have a stable order: active permit, unexpired permit, matching
agent, supported currency, positive amount, allowed merchant, allowed category,
per-purchase limit, remaining budget. The corresponding denial codes are
`permit_revoked`, `permit_expired`, `agent_mismatch`, `unsupported_currency`,
`invalid_amount`, `merchant_not_allowed`, `category_not_allowed`,
`per_purchase_limit_exceeded`, and `insufficient_budget`.

A purchase **above** `approval_threshold_cents` becomes `pending_approval`;
null disables approval and zero requires approval for every positive purchase.
Equality with a threshold or spending limit is allowed. Pending requests do not
reserve anything. Approval repeats every policy check inside the transaction;
if policy no longer permits the purchase it becomes `denied` with a reason.
Policy denials return HTTP 200 with their persisted state; invalid state
transitions and conflicting idempotency keys return 409.

```text
proposal -> denied | pending_approval | authorized
pending_approval -> authorized | denied | rejected | cancelled
authorized -> fulfilled | failed | cancelled
```

Terminal states cannot transition again. Remaining budget equals total limit
minus fulfilled spend minus authorized reservations. Fulfillment moves reserved
money to spent without charging the budget twice. Failure and cancellation
release the reservation. Revoking a permit cancels all pending/authorized
requests atomically and preserves fulfilled spend. Revocation is idempotent.
Expiry blocks submissions and approvals; it does not automatically release an
existing reservation. Those reservations remain accounted for until explicitly
cancelled, failed, fulfilled, or revoked. There is no settlement worker yet.

Every timestamp must have an offset on input and is normalized to UTC. SQLite
stores naive UTC through an explicit SQLAlchemy type that restores UTC awareness
on read. Permit expiry is inclusive: at or after `expires_at`, new authority is
refused.

## Transactions, concurrency and idempotency

All spending API reads and writes use `spending_service(engine)`. It opens a fresh
session and executes `BEGIN IMMEDIATE` **before reading any state**, holding
SQLite's database-wide write lock through commit. Competing connections/processes
sharing the same local database file wait up to 30 seconds, then read the updated
budget. This prevents two $8 proposals or approvals from consuming a $10 budget.
The policy check, request state, reservation accounting, and idempotency decision
share one transaction. Errors roll back. FastAPI uses a function-scoped dependency
to commit before sending a success response. Database unavailability/lock timeout
returns a generic 503; retry with the same idempotency key.

A database unique constraint on `(agent_id, external_request_id)` backs retries.
An identical normalized payload returns the existing request's current state;
changed details return 409. A retry never reserves twice, even after cancellation,
denial, fulfillment, or permit revocation. Use a new key for a new proposal.

The database file is the serialization boundary. Separate copies, network
filesystems, or writes bypassing this service are unsupported. SQLite serializes
all spending operations, including reads, so this is intentionally a simple,
low-throughput MVP. Non-SQLite authorization engines fail closed until an
appropriate row-locking strategy is implemented. Use a local file-backed SQLite
database; independent in-memory connections do not share this boundary.

Trusted future settlement code may call these methods **inside the same context**:

```python
from app.core.database import get_engine
from app.services.spending import spending_service

with spending_service(get_engine()) as service:
    service.mark_fulfilled(request_id)  # authorized -> fulfilled
# Or service.mark_failed(request_id) inside a separate context after a real failure.
```

Neither method performs a payment. Do not call either to simulate purchases.

## Reproducible curl walkthrough

Run the server as above. In a second terminal, from `backend/` with its virtual
environment active, enter the credentials you put in `.env`. These prompts hide
input. Do not enable shell tracing (`set -x`):

```bash
read -rsp 'Development owner credential: ' OWNER_TOKEN; echo
read -rsp 'Development agent credential: ' AGENT_TOKEN; echo
BASE=http://127.0.0.1:8000
EXPIRY=$(python -c 'from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc)+timedelta(days=1)).isoformat())')

# Create a $100 permit, $30 per purchase, owner approval above $15.
PERMIT_JSON=$(curl --fail-with-body -sS "$BASE/api/permits" \
  -H "Authorization: Bearer $OWNER_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"agent_id\":\"shopping-agent\",\"name\":\"Office supplies\",\"currency\":\"USD\",\"total_limit_cents\":10000,\"per_purchase_limit_cents\":3000,\"allowed_merchants\":[\"office-store\"],\"allowed_categories\":[\"supplies\"],\"approval_threshold_cents\":1500,\"expires_at\":\"$EXPIRY\"}")
PERMIT_ID=$(printf '%s' "$PERMIT_JSON" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
printf '%s\n' "$PERMIT_JSON"

# $8: authorized; reserves 800 cents. Retry this exact request to see idempotency.
curl --fail-with-body -sS "$BASE/api/purchase-requests" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"permit_id\":\"$PERMIT_ID\",\"agent_id\":\"shopping-agent\",\"merchant\":\"office-store\",\"category\":\"supplies\",\"product_id\":\"paper\",\"amount_cents\":800,\"currency\":\"USD\",\"external_request_id\":\"$PERMIT_ID-paper-1\"}"

# $20: pending_approval; no reservation yet.
PENDING_JSON=$(curl --fail-with-body -sS "$BASE/api/purchase-requests" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"permit_id\":\"$PERMIT_ID\",\"agent_id\":\"shopping-agent\",\"merchant\":\"office-store\",\"category\":\"supplies\",\"product_id\":\"pens\",\"amount_cents\":2000,\"currency\":\"USD\",\"external_request_id\":\"$PERMIT_ID-pens-1\"}")
PENDING_ID=$(printf '%s' "$PENDING_JSON" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
printf '%s\n' "$PENDING_JSON"

# Owner explicitly approves. Agent credential here would receive 403.
curl --fail-with-body -sS -X POST "$BASE/api/purchase-requests/$PENDING_ID/approve" \
  -H "Authorization: Bearer $OWNER_TOKEN"

# Disallowed merchant: denied with merchant_not_allowed; reserves nothing.
curl --fail-with-body -sS "$BASE/api/purchase-requests" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"permit_id\":\"$PERMIT_ID\",\"agent_id\":\"shopping-agent\",\"merchant\":\"other-store\",\"category\":\"supplies\",\"product_id\":\"paper\",\"amount_cents\":800,\"currency\":\"USD\",\"external_request_id\":\"$PERMIT_ID-denied-1\"}"

# Summary: spent 0, reserved 2800, remaining 7200 cents.
curl --fail-with-body -sS "$BASE/api/permits/$PERMIT_ID" -H "Authorization: Bearer $OWNER_TOKEN"

# Release the $20 reservation; remaining is now 9200 cents.
curl --fail-with-body -sS -X POST "$BASE/api/purchase-requests/$PENDING_ID/cancel" \
  -H "Authorization: Bearer $AGENT_TOKEN"

# Revoke; cancels the remaining $8 reservation.
curl --fail-with-body -sS -X POST "$BASE/api/permits/$PERMIT_ID/revoke" \
  -H "Authorization: Bearer $OWNER_TOKEN"
unset OWNER_TOKEN AGENT_TOKEN
```

## Tests and layout

From `backend/`, after installing development dependencies:

```bash
python -m pytest -q
```

Tests retain Milestone 1 health/configuration/database checks and cover policy
reasons, role boundaries, strict inputs, owner visibility, idempotency, reservation
release, terminal states, approval rechecks, persistence, UTC, rollback, and
concurrent $8 requests/approvals against $10. Concurrency tests use independent
engines against the same temporary SQLite file. Test databases are isolated from
the development database.

```text
backend/app/
  main.py                 # App factory, CORS, safe error responses
  api/health.py           # Liveness
  api/spending.py         # Thin HTTP routes
  core/config.py          # Typed environment settings
  core/security.py        # Explicit development identity guards
  core/database.py        # Engine and reusable sessions
  core/init_db.py         # Explicit local schema initialization
  models/spending.py      # Persistent permits, normalized lists, proposals
  schemas/spending.py     # Strict inputs and public response schemas
  services/spending.py    # Transactions, policy, accounting and transitions
backend/tests/
```

There is no frontend, Bitrefill, Zcash, AI orchestration, payment integration,
or fake purchase implementation.
