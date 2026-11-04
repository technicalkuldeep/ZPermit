# ZPermit application integration map

The React client uses the FastAPI contracts below. `/openapi.json` is the source
of truth. All protected requests carry a role-specific local development Bearer
credential; Bitrefill keys never leave the server. Dev credentials remain in tab
memory, not local/session storage, URLs, QR codes, analytics or frontend builds.

| Screen / operation | Existing or additive HTTP contract | Role / behavior |
| --- | --- | --- |
| Welcome | GET /api/workspace; GET /api/workspace/identity | Owner snapshot; optional agent identity validation |
| Dashboard / history | GET /api/workspace | Additive owner-scoped aggregation of existing tables; no external calls |
| Create permit | POST /api/permits | Owner; strict PermitCreate, integer USD cents |
| List / inspect permit | GET /api/permits; GET /api/permits/{id} | Owner; server-calculated spending summary |
| Revoke | POST /api/permits/{id}/revoke | Owner; existing transactional cancellation/reservation rules |
| Product search | GET /api/bitrefill/products?query=&intent=&country= | Existing authenticated MCP reads, id is product slug |
| Product details | GET /api/bitrefill/products/{id} | Face package currency distinct from payment_currency and payment_price_cents |
| USD account credit | GET /api/bitrefill/balance | Owner; authenticated spendable USD cents, unavailable stays unavailable |
| Agent task | Search -> details -> POST /api/purchase-requests -> POST /api/bitrefill/purchase-previews | Agent credential only; genuine deterministic executor, no LLM or provider-write access |
| Owner decision | POST /api/purchase-requests/{id}/approve or /reject | Owner confirmation; policy re-evaluated |
| Cancel request | POST /api/purchase-requests/{id}/cancel | Existing owner/agent boundary; unresolved executions retain reservation |
| Checkout readiness | Existing previews + /api/workspace.checkout | Always blocked for current unbounded provider contract |
| Execute boundary | POST /api/bitrefill/purchase-previews/{id}/execute | Existing guarded owner route; UI never invokes it |
| Execution reconciliation | POST /api/bitrefill/executions/{id}/reconcile | Owner; read-only provider invoice check; existing settlement rules |
| Existing account invoice | GET /api/bitrefill/invoices/{uuid} | Additive owner-only REST projection, no attachment or settlement |
| Mobile request | POST /api/zcash/mobile/payment-requests | Existing owner service; immutable terms, genuine utest1 checksum validation |
| Saved mobile request | GET /api/zcash/mobile/payment-requests/{id} | Owner; ZIP-321 URI, no signing authority |
| QR | GET /api/zcash/mobile/payment-requests/{id}/qr.png | Authenticated Blob fetch -> temporary object URL; no credential in image URL |
| Network readiness | GET /api/zcash/public/readiness | Existing NU7/Ironwood trusted remote read, not a local Zebra node |
| Associate genuine txid | POST /api/zcash/mobile/payment-requests/{id}/evidence | Existing owner-reported association, not private-detail proof |
| Standalone real txid | POST /api/zcash/public/transactions | Existing read-only public evidence workflow |
| Track confirmations | POST /api/zcash/public/transactions/{id}/refresh | Latest-check flag distinguishes stale evidence; no wallet send |

The workspace aggregator reads the existing permit, purchase, preview, execution,
phone-request and observation tables inside the existing SQLite transaction
boundary. It does not duplicate policy logic, calculate its own reservation
balances, or join phone observations to USD settlement. The account-invoice route
only reads genuine provider records; the experimental unpaid invoice is not
fabricated or attached to a permit retroactively.

A submitted task uses a stable external_request_id for the same proposal. It
returns persisted authorized/pending/denied state. Catalog prices are indicative;
the owner-selected category is a proposal label, never invented provider metadata.
For missing types, recipient requirements, prepayment products or uncertain
prices, checkout remains blocked. No call to buy-products, invoice creation,
invoice pay, local-wallet broadcast or mobile signing exists in the client.

Development Vite uses a loopback proxy to port 8000. After production build,
FastAPI serves frontend/dist on the same origin. No cloud hosting is configured.
