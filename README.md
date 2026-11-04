# ZPermit

**Public URL: NOT DEPLOYED / NOT VERIFIED.**

[Deploy the isolated public demo](docs/DEPLOYMENT.md) · [Copy-paste submission](docs/SUBMISSION.md) · [2–3 minute demo](docs/DEMO_SCRIPT.md)

**Give your agent a budget. Keep the authority.**

ZPermit is a local spending-permission workspace: an agent discovers a real
product, proposes an indicative USD amount, and receives a persisted policy
decision. The owner manages budgets, approvals and evidence. Zingo Mobile keeps
Zcash testnet signing on the owner's phone.

**No purchase or wallet send is simulated as successful. Bitrefill live checkout
remains blocked because the provider contract does not guarantee a maximum USD
debit.** One genuine, unpaid Swiggy invoice from an earlier explicitly approved
experiment can be inspected read-only. Its raw BTC-labelled price is not USD.

## Start the application

Prerequisites: Python 3.11+, Node 22.12+ (Node 24 tested), and the existing backend
configuration. From a fresh checkout, install dependencies first:

```bash
cd ~/Projects/ZPermit/backend
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
# Only if .env does not already exist; never overwrite your configured account key.
cp -n .env.example .env
cd ../frontend
npm ci
```

Keep `backend/.env` private. Configure distinct
`ZPERMIT_DEV_OWNER_CREDENTIAL` and `ZPERMIT_DEV_AGENT_CREDENTIAL`,
`BITREFILL_API_KEY` for real catalog/account reads, and
`ZPERMIT_ZCASH_PUBLIC_READS_ENABLED=true` for public testnet evidence.
Keep `BITREFILL_LIVE_PURCHASES_ENABLED=false` and all wallet broadcast flags false.
Do not put the Bitrefill key in any `VITE_` variable or browser form.

The existing public address/transaction decoder is already built in this workspace.
If absent, build this read-only utility (not a wallet, validator or node):

```bash
cd ~/Projects/ZPermit/backend
cargo build --locked --release --manifest-path tools/zcash-public-inspect/Cargo.toml
```

Terminal 1:

```bash
cd ~/Projects/ZPermit/backend
.venv/bin/python -m app.core.init_db
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```bash
cd ~/Projects/ZPermit/frontend
npm run dev
```

Open **http://127.0.0.1:5173**. Leave Backend URL empty to use the local proxy.
Enter the development owner and separate agent credentials from your backend
configuration. The provider key is never requested. Credentials remain only in
tab memory and clear on reload/disconnect. This is local-development role
separation, **not production authentication**. Use a trusted machine and keep the
API bound to loopback. The phone only needs the QR/URI, not backend access.

For a single-origin production build, without deploying anywhere:

```bash
cd ~/Projects/ZPermit/frontend
npm run build
cd ../backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000** after starting/restarting FastAPI. It serves the
built frontend when `frontend/dist` exists. API docs remain at `/docs`, OpenAPI at
`/openapi.json`, and health at `/health`. SQLite paths are relative to backend's
working directory. Schema initialization is additive create_all, not migration.

## The product journey

1. **Connect.** Authenticate the owner; optionally connect the limited development
   agent credential. No wallet connection or seed import is needed.
2. **Create a spending permit.** Set agent, total USD budget, per-purchase maximum,
   exact merchant/product slugs, category labels, expiration and approval threshold.
   For Swiggy use merchant `swiggy-money-india`. Unknown provider type is not
   invented; a chosen proposal category does not certify provider metadata.
3. **Ask the agent.** In Agent requests, choose a permit/category and run “Find a
   ₹50 Swiggy Money gift card and buy it if it fits my permitted spending rules.”
   This is an honest deterministic task executor for Swiggy, Flipkart and Google
   Play India, not an LLM. Shop supports broader real product search/details.
4. **Inspect the decision.** Authorized reserves USD cents, pending requires an
   owner decision, denied records the exact reason. Approval repeats policy checks.
   Request readiness explains why authorization has not resulted in a purchase.
5. **Inspect real provider evidence.** Read the existing invoice in Evidence &
   activity. Unpaid, not-delivered and raw BTC amount remain distinct from USD
   credit, permit authorization or successful fulfillment.
6. **Pay from your phone, separately.** Supply a genuine recipient utest1 address,
   exact TAZ amount and optional non-secret memo. Generate/download a ZIP-321 QR.
   Scan with Zingo Mobile; explicitly review network, Ironwood, recipient, amount,
   memo and wallet-calculated fee. If URI handling is unsupported, cancel the
   incorrect draft and use the manual copy-address/TAZ/memo fallback.
7. **Verify a real txid.** After signing/sending on the phone, paste its genuine
   lowercase txid. Refresh confirmations. Public evidence cannot establish private
   recipient, amount, memo or sender, and never settles a USD reservation.

The Zcash flow is testnet only, independent of Bitrefill funding. No new wallet,
local Zebra node, seed phrase, viewing key or automatic broadcast is involved.
Never resend a phone payment blindly after an ambiguous result.

## Caps, approvals and uncertain outcomes

All permits and purchases use strict integer **USD cents**. INR 50 face value is
not USD 50; the current catalog payment price is a separate indicative USD amount.
Available budget = total limit − fulfilled spending − authorized reservations.
SQLite BEGIN IMMEDIATE protects concurrent decisions across processes sharing one
local database. Pending requests do not reserve. Approval threshold equality is
allowed; a purchase **above** the threshold requires approval. Zero requires
approval for every positive proposal; blank/null disables the checkpoint.

Expiry/revocation, matching agent, currency, positive amount, exact merchants and
categories, per-purchase cap and remaining budget are enforced by the existing
backend. Identical `(agent_id, external_request_id)` submissions are idempotent;
changed payloads conflict. Authorized does not mean paid. Unresolved provider
execution records keep reservations even through cancellation/revocation.

A durable unique claim precedes any possible checkout execution. Unknown outcomes
freeze further execution; no blind non-idempotent retry is allowed. Delivery
failure alone is not refund evidence. Only verified reconciliation can settle or
release an initiated reservation. Current provider writes are blocked entirely.

## Actual versus planned

| Working now | Not claimed / still blocked |
| --- | --- |
| React/Vite/TypeScript/Tailwind dashboard and persisted owner workspace | Production identity, hosting or multi-tenant guarantees |
| Permit creation/read/revoke, decisions, approval and concurrent reservations | Editing historical permits or bypassing existing accounting |
| Real authenticated catalog, indicative USD prices and balance reads | Guaranteed final Bitrefill charge or live purchase execution |
| Deterministic agent discovery/proposal/readiness | Autonomous AI payment authority |
| Genuine account invoice lookup and execution reconciliation | Paid Swiggy product or automatic code delivery |
| ZIP-321, local QR, phone-wallet manual fallback | Control of Zingo, phone balance access or verified link support |
| Real NU7/Ironwood txid reads and confirmations | Private receipt verification, local consensus validation or automatic USD settlement |

## Verify

```bash
cd ~/Projects/ZPermit/backend
.venv/bin/pytest -q
cd ../frontend
npm run typecheck
npm test
npm run build
```

Browser integration tests launch a loopback backend with an isolated temporary
SQLite database and randomly generated development credentials. They use real
policy HTTP routes and never call provider writes. Provider-dependent read tests
are opt-in; see [verification notes](docs/VERIFICATION.md).

```bash
cd ~/Projects/ZPermit/frontend
npx playwright install chromium
npm run test:browser
```

Read-only provider verification:

```bash
cd ~/Projects/ZPermit/backend
.venv/bin/python -m app.integrations.verify_bitrefill
.venv/bin/python -m app.integrations.verify_bitrefill_rest --invoice-id 1f81dedb-ea5d-4065-9332-81d573e98f3a
.venv/bin/python -m app.integrations.verify_public_testnet
```

External network availability, configured credentials, supported testnet and the
existing decoder are required. A failed latest confirmation check retains prior
evidence and is visibly marked stale. Nothing is fabricated to hide a failure.

## Architecture and submission

- [Actual API integration map](docs/INTEGRATION_MAP.md)
- [Privacy and trust](docs/PRIVACY.md)
- [3-minute demo](docs/DEMO.md)
- [30-day roadmap](docs/ROADMAP.md)
- [Feedback](FEEDBACK.md)
- [Bitrefill checkout decision and blockers](backend/docs/bitrefill-checkout-recommendation.md)
- [Bitrefill contract](backend/docs/bitrefill-contract.md)
- [Zingo Mobile handoff and evidence limits](backend/docs/zingo-public-testnet.md)
- [NU7 compatibility](backend/docs/zcash-compatibility.md)

Frontend: `frontend/src/{App,api,agent,types}`. Backend: existing services in
`backend/app/services`; additive owner reads in `api/workspace.py`. The existing
local-wallet adapter remains separate and is not used for phone signing.


## Deadline deployment: isolated public demo

The private local application above continues using your local configuration.
Never expose it publicly with its development credentials or funded account.
The separate `app.public_demo:create_demo_app` entrypoint runs the same spending
engine in fresh temporary visitor databases. Its catalogue is clearly labelled
sample data; account balance, invoices, wallet/evidence routes and purchases are
blocked. Sessions expire after 30 minutes, and request/session limits constrain
abuse. No real account key, wallet, database or local .env is deployed.

The root Dockerfile builds React once and runs FastAPI on 0.0.0.0 with PORT;
`render.yaml` defines a single Docker service. It uses no cloud database or
persistent private volume. SPA navigation refreshes and assets are served by the
same process. Hosting login/GitHub authorization remains a manual boundary:
[exact Render steps](docs/DEPLOYMENT.md). Docker is unavailable in this environment,
so an image build is not claimed as verified; the production frontend and public
ASGI entrypoint are checked independently.

For an isolated local preview (port 8001, separate from private app on 8000):

```bash
cd ~/Projects/ZPermit/backend
ZPERMIT_PUBLIC_DEMO=true .venv/bin/uvicorn app.public_demo:create_demo_app --factory --host 127.0.0.1 --port 8001 --workers 1 --no-access-log
```

Do not export or attach real provider/development/wallet credentials to that
process. The public entrypoint refuses them and does not load the local .env.
Click Start isolated demo. Demo agent identity is fixed to demo-agent; local
permit forms use the actual server-reported agent and cannot silently edit it.
Older permits for a different identity remain intact but cannot be selected by
that agent. Create a matching permit rather than bypassing authentication.

Submission documents: [privacy and trust](docs/PRIVACY_AND_TRUST.md),
[demo script](docs/DEMO_SCRIPT.md), [submission sheet](docs/SUBMISSION.md),
[30-day roadmap](docs/ROADMAP_30_DAYS.md), and [developer feedback](FEEDBACK.md).
The real Swiggy invoice is unpaid and the own-wallet txid is still missing.
