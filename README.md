# ZPermit

Privacy-conscious AI spending authorization platform for the Free Society Hackathon.
Milestones 1–3 provide FastAPI spending authorization and a server-owned Bitrefill
integration boundary. **Live checkout remains blocked pending contract verification;
no payments or purchases have been executed.**

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
or catalog provenance. Bitrefill discovery and preparation are described below; proposal values alone
never establish a verified checkout price.

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
release the reservation. Revoking a permit cancels pending/authorized requests atomically and preserves
fulfilled spend. Requests with an initiated or uncertain Bitrefill checkout keep
their reservation until reconciliation; cancellation cannot release those funds. Revocation is idempotent.
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

There is no frontend, Zcash, AI orchestration, payment execution, or fake purchase
implementation. Bitrefill live checkout is explicitly blocked as explained below.

## Milestone 3: Bitrefill discovery and guarded preparation

Official references: [eCommerce MCP](https://docs.bitrefill.com/docs/ecommerce-mcp),
[API overview](https://docs.bitrefill.com/docs/api-overview),
[partner guide](https://docs.bitrefill.com/docs/mcp-partner-integration-guide).
The backend uses the official hosted MCP at `https://api.bitrefill.com/mcp` with a
server-side API key in the Authorization header. It decodes JSON and TOON read
results, including SSE envelopes. Credentials never go in URLs or agent payloads.

**Current blocker:** the public documentation does not establish a complete
pre-checkout quote contract proving final USD cost, fees, availability and quote
validity, or a checkout price-bound guarantee. No Bitrefill credential is currently
configured to inspect the authenticated contract. Discovery uses minimal documented
fields and rejects unsupported response layouts. Live preparation persists a
**blocked** preview (`quote_contract_unverified`) with null cost, rather than
inventing a quote. Live checkout cannot dispatch `buy-products`, even if its
safety flag is enabled. See [contract verification and blockers](backend/docs/bitrefill-contract.md).

After updating dependencies, rerun schema initialization. This adds the preview
and execution tables to an existing Milestone 2 database without altering its
permit/request tables or data:

```bash
cd backend
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m app.core.init_db
```

Additional environment settings (keep real keys only in `.env` or secret storage):

| Variable | Default | Purpose |
| --- | --- | --- |
| `BITREFILL_API_KEY` | unset | Server account API key; required for real reads |
| `BITREFILL_LIVE_PURCHASES_ENABLED` | `false` | Necessary, never sufficient, for checkout |
| `ZPERMIT_BITREFILL_TIMEOUT_SECONDS` | `10` | Per-network-operation timeout, 0.1–30 seconds |
| `ZPERMIT_BITREFILL_PREVIEW_TTL_SECONDS` | `60` | Local preview lifetime cap, 1–300 seconds |

The two unprefixed Bitrefill variables also accept `ZPERMIT_` aliases. Restart
after setting them. Missing/rejected credentials return 503; provider timeouts
return 504. Read-only transient failures retry at most once with backoff; rate
limits do not retry automatically. Errors/logs contain fixed codes, never raw
provider messages or bodies. Read calls do not create orders or reserve funds.
OAuth guest accounts and invoice access-token storage are not supported.

With `BASE`, `AGENT_TOKEN`, and `OWNER_TOKEN` set as in the earlier walkthrough:

```bash
# Read-only search. intent is required by the current MCP partner guide.
curl --fail-with-body -sS --get "$BASE/api/bitrefill/products" \
  -H "Authorization: Bearer $AGENT_TOKEN" \
  --data-urlencode 'query=Amazon' --data-urlencode 'country=US' \
  --data-urlencode 'intent=Find a US gift card for an owner-approved purchase'

# Use an exact id returned by search; the ID below is a documented example.
curl --fail-with-body -sS "$BASE/api/bitrefill/products/amazon_com-usa" \
  -H "Authorization: Bearer $AGENT_TOKEN"
```

Search can include `product_type` if supported by the account's actual tool.
Gift cards, phone refills and eSIMs share the normalized product response. The
response exposes available denomination labels/ranges and recipient requirements
when present. Unknown availability/cost stays null. It never forwards raw objects,
gift-card codes, invoice tokens, checkout links or eSIM installation material.

The exact product slug is the permit's merchant identifier. The documented
product type (`gift_card`, `phone_refill` or `esim`) is its category. No brand-name
substring inference is performed. Unknown types block preparation. Use these
server-returned values to create the permit and proposal; a proposed product ID,
merchant or category must match independently fetched product information.

Preparation accepts an **existing** visible purchase request. It can run while
owner approval is pending but cannot reserve pending funds or perform checkout:

```bash
# Set REQUEST_ID to an existing ZPermit request. Set denomination to a value
# returned by product details, not the full compound package_id.
curl --fail-with-body -sS "$BASE/api/bitrefill/purchase-previews" \
  -H "Authorization: Bearer $AGENT_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"purchase_request_id\":\"$REQUEST_ID\",\"denomination\":\"10\"}"

# For a required recipient, add recipient to preparation and later confirmation.
# Recipient values are not persisted: only a keyed digest binds the confirmation.
```

A ready preview (once the live quote contract is verified) binds product snapshot,
denomination, recipient digest, exact USD cost, payment method and expiry with a
fingerprint. The workflow requires the quote to equal the request's immutable
amount exactly. If a price differs, cancel the old uninitiated request and create
a new proposal using the verified amount; no authorization or idempotency payload
is silently changed. New cost must pass all permit rules and approval thresholds.
A preview never changes the budget itself. Re-preparing creates a new preview and
fingerprint; only one execution is allowed across all previews of that request.

Owner approval of the spending request and owner confirmation of the exact
checkout are separate steps:

```bash
# Only if the spending request is pending_approval:
curl --fail-with-body -sS -X POST "$BASE/api/purchase-requests/$REQUEST_ID/approve" \
  -H "Authorization: Bearer $OWNER_TOKEN"

# Future owner-confirmed checkout boundary. Currently returns 503 when disabled
# or blocked by the live contract, and NEVER produces a fake invoice.
# PREVIEW_ID and FINGERPRINT must come from a ready, unexpired preview.
curl --fail-with-body -sS "$BASE/api/bitrefill/purchase-previews/$PREVIEW_ID/execute" \
  -H "Authorization: Bearer $OWNER_TOKEN" -H 'Content-Type: application/json' \
  -d "{\"preview_fingerprint\":\"$FINGERPRINT\",\"confirm\":true}"
```

A normal agent credential receives 403 for execution. The service re-fetches
fresh details/quote and rechecks the permit, expiry, approval, remaining budget,
product, exact price and preview before committing a unique initiating record.
An increased or otherwise changed price requires fresh preparation and consent.
The initiating record is durable before a possible write. Uncertain outcomes
remain reserved and cannot be retried, cancelled or force-released.

To eventually enable real checkout: first resolve and test every contract blocker
listed in the linked verification document, including billing requirements and a
provider-enforced exact-price guarantee. Then explicitly configure the safety
flag, restart, prepare a fresh quote, approve any pending spending request, review
its precise product/denomination/USD price and submit the owner confirmation with
that preview's fingerprint. **Enabling the flag alone currently cannot purchase.**
No balance, cashback, saved-card charge, x402 settlement or payment route exists.

Owner-only execution lookup and reconciliation (for genuine persisted executions):

```bash
curl --fail-with-body -sS "$BASE/api/bitrefill/executions/$EXECUTION_ID" \
  -H "Authorization: Bearer $OWNER_TOKEN"
curl --fail-with-body -sS -X POST "$BASE/api/bitrefill/executions/$EXECUTION_ID/reconcile" \
  -H "Authorization: Bearer $OWNER_TOKEN"
```

Poll no faster than every 10 seconds. Invoice created, unpaid, payment detected,
paid, and delivered are distinct; invoice creation alone never fulfills a request.
Completion requires exactly one delivered order for the expected product. Failed
or blocked statuses retain funds; only a verified refunded order releases a failed
purchase here. Unknown or contradictory statuses require reconciliation. Terminal
settlement is idempotent. If the provider never returned an invoice ID, contact
Bitrefill support: there is no undocumented lookup, manual attachment, automatic
retry or unsafe force-release path. A process crash may leave `initiating`; this
also holds the budget and needs reconciliation. No background poller or secret
redemption delivery endpoint is included.

All automated provider tests are isolated mocks with real network transports
blocked. Normalized quote fixtures test the security workflow; they are not
assertions about Bitrefill's production pricing schema. Documentation and the
public schema were fetched live, but authenticated catalog reads and invoices
have **not** been verified live because no credential is configured. No live
`buy-products` call was made and no funds or credits were spent.

Optional read-only verification from `backend/`:

```bash
python -m app.integrations.verify_bitrefill
```

This skips without a credential. With a credential it calls only search and
details, prints a count and product ID, and never creates an invoice or pays.
