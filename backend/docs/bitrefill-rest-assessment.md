# REST two-stage balance assessment — 2026-11-04

**Historical assessment before invoice creation.** The one creation approval below
was subsequently granted and consumed; it is not permission to create another
invoice. See [latest decision](bitrefill-checkout-recommendation.md) and the saved
experiment records for verified creation and current unpaid BTC invoice status.

## Decision

Two-stage creation/payment is documented, including personal Bearer auth. Live
personal REST **read access** works. Live invoice creation and an enforceable USD
maximum debit remain **unverified**. No REST checkout adapter is enabled or wired
into ZPermit. No invoice was created or paid during this assessment.

## Official sources examined

- https://docs.bitrefill.com/docs/integration-flow
- https://docs.bitrefill.com/docs/quickstart-2
- https://docs.bitrefill.com/docs/api-overview
- https://docs.bitrefill.com/docs/core-concepts
- https://docs.bitrefill.com/reference/post_invoices
- https://docs.bitrefill.com/reference/post_invoices-id-pay
- https://docs.bitrefill.com/reference/get_invoices
- https://docs.bitrefill.com/reference/get_accounts-balance

The embedded OpenAPI JSON in the invoice-create and invoice-pay reference pages
was examined, not just rendered examples. It supports BasicAuth OR BearerAuth.
Its documented default host is api-bitrefill.com; the quickstart uses
api.bitrefill.com. Authenticated GETs succeeded on both without redirects.
Personal access is documented for small personal purchases. There is no evidence
that Business credentials are mandatory for this flow, but GET permission does
not prove POST permission for this particular account.

## Authenticated read observations

GETs only; server-held key in Authorization; no codes or invoice contents printed:

| Route (both hosts) | Result |
| --- | --- |
| /v2/ping | HTTP 200; root message=pong (not data.message) |
| /v2/accounts/balance | HTTP 200; data.balance=0, data.currency=BTC |
| /v2/products/swiggy-money-india | HTTP 200; currency=INR, in_stock=true |
| /v2/invoices?limit=1 | HTTP 200; data=[] |

The actual INR 50 package is packages[].id=`swiggy-money-india<&>50`,
value="50". Its price was 684, with no payment currency/unit on that package.
That number is NOT 684 USD cents and is not used in spending calculations.
MCP previously confirmed the separate USD account contains 2500 USD cents.
REST's zero BTC primary balance does not mean USD is empty. There is no documented
USD sub-account selector in the examined REST creation/payment schemas. We do not
copy MCP's balance_currency argument into REST and assume it works.

## Documented invoice response and missing guarantees

The create/pay 200 response points to data -> Invoice:

| Meaning | Documented field | Limitation |
| --- | --- | --- |
| Invoice identifier | data.id (string) | No account-specific invoice observed |
| Amount | data.payment.price (number; example 10) | Need actual USD response and verified units/fee inclusion |
| Currency | data.payment.currency (string; example USD) | USD example is not this account's currency selection guarantee |
| Method | data.payment.method | Must equal balance |
| Payment state | data.payment.status (example unpaid) | Distinct from delivery/invoice state |
| Invoice state | data.status | Schema example not_delivered differs from guide examples |
| Product/face value | data.orders[].product.id/value/currency | Must bind exactly one INR 50 order to expected product |
| Order state | data.orders[].status | created is not delivered |
| Times | created_time, completed_time | Neither is an invoice-expiration deadline |
| Invoice expiration | No field in examined Invoice schema | Never substitute gift-card expiration or local TTL |
| Immutable charge / fee-inclusive maximum | No guarantee found | Cannot assert price lock or enforce by a GET-before-POST alone |

POST /v2/invoices accepts payment_method=balance and auto_pay=false. The guide
says this leaves manual payment for a separate call. Its OpenAPI products field
is incorrectly typed object while examples/guides use an array; package_id is
incorrectly typed number while live package IDs and guide examples are strings.
These inconsistencies require observing the real response, not coercing IDs.

POST /v2/invoices/{id}/pay has an unused optional object body, no amount,
currency, expected-price/version or max-debit argument. HTTP 404 means not found
OR already paid; it does not prove a previous attempt failed. Documentation says
it pays an unpaid balance invoice, which suggests settlement of its recorded
amount, but does NOT explicitly guarantee no repricing, fees, conversion or
sub-account change before payment. A successful unpaid invoice capture would
verify response shape and creation permission, not settle those contractual gaps.
A repeated GET with the same price also cannot prove future immutability.

## Safety requirements for a future adapter (not implemented)

Reuse the existing policy/reservation/owner checks and transaction protection;
keep the agent behind ZPermit and credentials/payment endpoints server-owned.
The current single claim models one create-and-possibly-debit attempt. A proper
two-stage adapter needs separate durable, one-shot create and pay claims and
invoice binding; do not simply treat unpaid invoice creation as purchase success.

| Event | Required behavior |
| --- | --- |
| Create timeout/crash | Retain reservation; freeze and manually reconcile account history; no blind second create |
| Unpaid invoice returned | Persist invoice/product/payment snapshot; do not mark paid, spent or delivered |
| USD total exceeds authorized reservation/cap | Never call pay; retain/reconcile invoice; no silent reservation increase |
| Wrong/missing currency, amount, identity or status | Block payment; never use INR denomination as USD cost |
| Price changed | Block; require a new reviewed authorization rather than silently refreshing |
| Expiration absent/unknown or expired | Block payment until provider expiration semantics are verified |
| Before pay | Recheck owner authorization, permit, exact product/denomination, USD sub-account, fees, balance and expiration; exact final debit must be provider-guaranteed |
| Concurrent/duplicate pay attempt | Atomic durable claim and uniqueness; at most one pay dispatch, even after process restart |
| Pay timeout/unknown/404 | Freeze; preserve reservation; read known invoice/account records; no automatic retry |
| Partial/failed delivery | Never infer refund from failure; retain funds until authoritative settlement/refund evidence |
| Complete + matching delivered order | Settle once using verified USD debit; unpaid is never fulfilled |

The existing MCP integration is unchanged and remains read-only. Existing tests
cover duplicate/concurrent initiation, timeout reservations, no automatic retry,
policy changes, invoice binding, delivery and refunds. New REST verifier tests
cover captured GET shapes, BTC/USD separation, no invented catalog USD price,
GET-only allowlist, no redirect/retry, errors and secret filtering. They do not
claim to test an unverified REST payment implementation.

## Next approval checkpoint

Only if the owner approves, dispatch exactly **one** request to:

POST https://api.bitrefill.com/v2/invoices

```json
{
  "products": [
    {
      "product_id": "swiggy-money-india",
      "package_id": "swiggy-money-india<&>50",
      "quantity": 1
    }
  ],
  "payment_method": "balance",
  "auto_pay": false
}
```

This is INR 50 face value; MCP's prior USD 0.55 was indicative only. No REST
currency selector is invented. The request is intended to create an unpaid
invoice with zero debit, as documented; actual behavior has not been verified.
Approval would cover creation only, followed by read-only inspection. It would
not authorize /pay, a retry, another invoice, account changes, enabling purchases,
or any spend. Stop on timeout or any unexpected state. Compare authenticated
USD balance before/after via MCP and inspect only whitelisted invoice fields.
Never print redemption information, tokens, URLs containing access tokens or keys.

Even if creation succeeds, keep payment blocked until USD selection, amount units,
fee inclusion, expiration and immutable maximum-debit semantics are established
by authoritative provider contract or a supported conditional-payment mechanism.

## Review

```sh
cd ~/Projects/ZPermit/backend
.venv/bin/pytest -q
.venv/bin/python -m app.integrations.verify_bitrefill_rest
```

The verifier can only GET four fixed routes. It never creates or pays an invoice
and makes no claim that successful reads grant checkout permission.
