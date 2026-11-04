# ZPermit — copy-paste submission sheet

**Title:** ZPermit

**One-line pitch:** Give your agent a budget. Keep the authority.

**Description (3 sentences):** ZPermit is a spending-permission web app and
minimal agent task runner that discovers products, proposes USD spending, and
enforces permit budgets, approvals and reservations before execution. Its private
local app uses real Bitrefill catalog/account reads and a Zingo Mobile testnet
payment handoff, while a separate public demo isolates visitors with explicitly
labelled sample data and no financial access. Live Bitrefill execution remains
blocked because a maximum USD debit is not contractually verified.

**Tracks:** Privacy track (Zcash); Agentic Commerce track (Bitrefill).

**Type:** Web App + Agent.

**Stack:** React, Vite, TypeScript, Tailwind CSS, Lucide; Python/FastAPI,
SQLAlchemy/SQLite, HTTPX, Bitrefill authenticated MCP/REST reads, ZIP-321,
Zingo Mobile signing handoff, public NU7/Ironwood lightwallet evidence; Docker.

**GitHub:** https://github.com/technicalkuldeep/ZPermit

**Public deployment URL:** [MISSING — paste only after actual HTTPS deployment
and smoke verification. No deployment is currently claimed.]

**Demo/video URL:** [MISSING — record and add the actual uploaded presentation.]

**Bitrefill technology used:** Hosted authenticated MCP search-products,
get-product-details, get-balances and get-invoice-by-id; authenticated REST
product/account/invoice reads. Exactly one earlier owner-approved
POST /v2/invoices with balance/auto_pay=false created a genuine unpaid invoice.
No MCP buy-products, invoice /pay or completed purchase is claimed.

**What was built:** Transactional spending permits, approval/reservation/revocation
policy engine; safe server-held Bitrefill adapters and checkout readiness;
minimal deterministic agent discovery/proposal executor; dashboard; ZIP-321
payment preparation/QR; public transaction observation/evidence association;
isolated public demo and Docker/Render configuration.

**What was reused:** FastAPI, SQLAlchemy, React/Vite/Tailwind/Lucide, Bitrefill
services, ZIP-321, Zcash protocol/official decoding libraries and lightwallet
service, and the owner's existing Zingo Mobile wallet. No new wallet, blockchain
or validator was built. The phone wallet remains independent of the backend.

**Maximum permitted spending:** No funds are spendable through the current
Bitrefill execution adapter. USD policy ceilings are owner-configured per permit;
example demonstration total $10 (1000 cents), maximum $1 (100 cents) per purchase,
exact swiggy-money-india merchant/category gift_card, and approval threshold $0
(requires owner approval for every positive proposal). This example is not a
provider-enforced payment guarantee. Per-purchase/total caps, expiry, agent match,
merchant/category checks and reservations are enforced by the real policy engine.

**Actual real Bitrefill invoice ID:** 1f81dedb-ea5d-4065-9332-81d573e98f3a

**Actual status:** UNPAID; not delivered. INR 50 Swiggy Money India x1. REST
payment.method=balance, payment.price=682, payment.currency=BTC. Raw BTC units and
an exact USD debit remain unverified. This invoice is NOT evidence of a completed
purchase and must not be submitted in a field requiring a paid invoice as though
it qualifies. Owner reports the Bitrefill track requires a completed purchase;
that requirement is currently unmet. Do not pay or create another invoice without
separate explicit authorization and a safe spending contract.

**Actual own-wallet Zcash testnet transaction ID:** [MISSING — no confirmed
transaction from our own wallet has been provided. Do not insert an unrelated
public transaction, test fixture or invented ID.]

**Optional viewing key:**

**30-day continuation milestone:** Resolve a provider-supported fee-inclusive USD
maximum-debit contract, implement one-shot bounded checkout and reconciliation,
add secure multi-user auth, validate installed Zingo Mobile handoff, and launch a
public beta after an independently reviewed genuine owner-approved transaction.

**Feedback:** Bitrefill Bearer authentication and USD balance/catalog reads
worked. Real response identity/country/type variations and INR face/USD payment
prices needed normalization; REST selected BTC on our unpaid balance invoice.
Non-idempotent auto-debit without a verified maximum charge or price lock blocks a
strictly capped autonomous agent. Requested improvements: max_total/minor-units,
explicit USD sub-account selection across APIs, bound/expiry-bearing quote IDs,
no-debit preview, execution idempotency and authoritative reconciliation lookup.
Zcash feedback: make installed wallet NU7/Ironwood and ZIP-321 compatibility clear,
and expose confirmation state without implying private recipient/amount proof.
See FEEDBACK.md for factual testing details and limitations.

## Missing submission requirements / final checks

- [ ] Commit and push reviewed source manually; confirm GitHub revision is public.
- [ ] Authorize hosting account/GitHub, deploy, verify actual public HTTPS URL.
- [ ] Record/upload a genuine 2–3 minute demo; add its URL if Stadium asks for one.
- [ ] Complete a real, separately approved Bitrefill purchase if required for track
      eligibility. The existing unpaid invoice does not satisfy this requirement.
- [ ] Send an owner-reviewed small testnet payment from Zingo Mobile and provide
      its actual txid/confirmations if required for Zcash track evidence.
- [ ] Fill the owner's actual team/contact/profile and any required media fields
      on the live Stadium form. The exact private submission form is not accessible
      in this session; do not assume extra fields or eligibility decisions.
- [ ] Confirm the optional viewing-key field remains blank unless explicitly
      supplied and approved for disclosure. Never submit a seed or spending key.

The public demo proves policy UX only. It is not a completed live commerce or
Zcash payment. Existing real account records stay local; only the minimal invoice
ID/status above is intentionally included at the owner's request.

Event source: [Free Society Hackathon](https://luma.com/freesocietyhackathon)
confirms the Privacy and Agentic Commerce tracks. Final eligibility/form details
must be checked with organizers/Stadium; a successful build alone is not evidence
of either track's live-payment requirements.
