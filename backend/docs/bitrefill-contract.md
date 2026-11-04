# Bitrefill contract verification — 2026-11-04

Read before implementing; recheck before enabling any checkout capability.

Official sources:

- https://docs.bitrefill.com/docs/ecommerce-mcp
- https://docs.bitrefill.com/docs/api-overview
- https://docs.bitrefill.com/docs/mcp-partner-integration-guide
- https://docs.bitrefill.com/docs/core-concepts
- https://docs.bitrefill.com/docs/quickstart-2
- https://github.com/bitrefill/cli (README documents decoded `products` search output)
- https://api.bitrefill.com/openapi.json (downloaded; describes x402, not a complete MCP output schema)
- https://github.com/toon-format/toon-python (official TOON decoder)

## Verified from documentation

Hosted server: `https://api.bitrefill.com/mcp`. Stateless Streamable HTTP,
JSON-RPC 2.0, `tools/call`; Accept must include JSON and event-stream. Read
responses are TOON; tool errors have `isError` and a JSON error object. An API
key in Authorization is supported for server-owned accounts. The newer partner
guide explicitly prohibits putting keys in URLs, superseding the older setup
example. OAuth guest lifecycle/access-token storage is deliberately not added.

Read tool inputs:

- `search-products`: query, required intent, country, optional product_type,
  per_page (20 here, below the documented maximum).
- `get-product-details`: product_id, currency (USD here).
- `get-invoice-by-id`: invoice_id, for the server account that owns it.

Minimal whitelisted read fields:

- Search root `products` (official CLI example); product id/name/type/country/
  currency from the product documentation. No guessed alternative field names.
- Details: product fields, packages[].package_value, range.min/max/step,
  recipient_type, presence of prepayment. Unknown layouts return a structured
  error rather than being guessed. REST `packages[].value` is NOT silently
  substituted for MCP `package_value`.
- Invoice: invoice_id, invoice_status, orders[].status; order product.id from
  core concepts binds settlement to a product. Without this binding the workflow
  retains funds and requires reconciliation.
- Documented invoice progress includes unpaid, payment_detected,
  payment_confirmed, pending and complete. Documented order states distinguish
  delivered, failed and refunded. Failed is not sufficient proof of refund.

These are documentation-based adapters, **not captured authenticated schemas**.
There is no configured Bitrefill credential in this workspace. If the actual
MCP nests or names these fields differently, the adapter fails closed and must
be updated from an authenticated, sanitized read capture, not guessed aliases.

## Explicit blockers

The public pages do not define a complete machine-verifiable priced detail
response establishing all of:

1. Product availability and authoritative product type/recipient requirements.
2. Exact final USD amount including fees for the chosen denomination and method.
3. Distinction between product face currency, display currency and charge currency.
4. Quote expiry/price-lock validity before invoice creation.
5. A supported checkout mechanism that binds the exact approved total (or a
   provider guarantee that an invoice cannot charge more than that total).
6. The current authenticated `buy-products` input/output schema. The older guide
   uses package_id; the newer partner guide uses package_value. Fiat card methods
   also require billing address fields; these are not guessed or collected yet.

Consequently `BitrefillClient.quote()` always returns a structured
`quote_contract_unverified` error; preparation persists a **blocked** preview
with no invented amount. `ensure_checkout_supported()` always refuses checkout.
`create_invoice()` also checks the disabled-by-default live switch. The transport
has a hard read-tool allowlist: it cannot dispatch buy-products at all in this
milestone. No balance, cashback, saved-card, invoice-pay or x402-pay call exists.

Switching the flag on does not resolve this blocker. Before shipping checkout,
verify those contracts with Bitrefill, implement and test the exact adapter and
billing inputs, and repeat contract review. Keep balance/cashback unavailable.
Do not substitute denomination, USDC, or a locally computed exchange rate for USD.

The internal `Quote` and mock provider are ZPermit domain contracts, not claims
about Bitrefill's response schema. Normalized test doubles exercise the complete
security boundary while the live adapter is blocked. There are no synthetic
invoices in production code.

## Reconciliation constraints

The execution row is durable before a possible network write. Unknown outcomes
retain funds and cannot be retried. If no invoice ID was returned/persisted, this
milestone cannot discover one by request id: provider idempotency/lookup support
is not documented. Contact provider support using the UTC initiation timestamp;
there is no unsafe manual invoice attachment or force-release endpoint.

When a genuine invoice ID is available, owner-only reconciliation uses a read
call. Complete plus exactly one delivered order for the expected product becomes
fulfilled. A verified refunded order for that product becomes failed/released.
A failed order, blocked invoice, missing association, malformed response, timeout,
or contradictory progress retains the budget. Public outputs contain no raw
provider objects, payment links, invoice access tokens, codes or eSIM activation
material. This milestone does not deliver purchased secret material to users.

## Test/live distinction

Automated tests block all real HTTP transports. Protocol fixtures exercise only
specified read fields, with JSON and TOON/SSE envelopes; they are not production
captures. Workflow tests use an explicitly named normalized MockProvider, including
mock initiation timeouts and statuses. They neither pay nor call live buy-products.

Only documentation and the public OpenAPI document were fetched live during
implementation. Authenticated product search/details and invoice lookup could not
be verified because no Bitrefill credentials are configured. No invoice was
created and no account funds/credits were used.

The authorization linearization point for future checkout is the committed
`initiating` record. Revocation before that point prevents initiation; revocation
afterwards cannot undo a possibly dispatched provider call and must preserve the
reservation. A database transaction cannot atomically revoke a remote side effect.
The final policy check and fresh quote precede that record; no provider write is
currently implemented, so this boundary has only been tested with isolated mocks.
