# Bitrefill authenticated contract review — 2026-11-04

Official contract: https://docs.bitrefill.com/docs/mcp-partner-integration-guide
Authenticated `tools/list`, `get-balances`, search and product details were read.
No buy-products call was made. Keys stay server-side in Authorization headers.

## Observed fields

Search products use `slug`; details use `id` with the same slug value. Both map
to Product.id (the stable policy identifier); conflicting identities fail closed.
Details expose country_code, currency (face currency), recipient_type=none,
in_stock, packages[].package_value/package_currency/payment_price/payment_currency,
and payment_methods.balance containing balance and cashback. Product type is
absent for these three products. It stays unknown; food categories, names and
country are not used to invent an authorization category.

Verified normalized products, all in stock and balance eligible:

| Product | Face value | Indicative USD payment cents |
| --- | --- | --- |
| swiggy-money-india | INR 50 | 55 |
| flipkart-india | INR 50 | 56 |
| google-play-india | INR 50 | 57 |

get-balances(currency=USD) returned balances[].payment_method=balance,
balance_currency=USD, amount="25.00", amount_base=2500, decimals=2. The adapter
checks both representations and rejects missing, contradictory or duplicate
USD balance entries. It never uses equivalent_in_product_currency or converts INR
into a permit amount. All reservations remain integer USD cents.

## Checkout remains blocked

Authenticated buy-products schema: cart_items (1..15), product_id slug,
package_value string, optional refill_input/bill_payment_id/gift; payment_method;
balance_currency (USD/EUR/BTC/XBT); return_payment_link; billing_address;
saved_fiat_card_id; coupon_code. Its annotations declare readOnlyHint=false,
destructiveHint=true, idempotentHint=false. Balance auto-debits immediately.
There is no verified max-charge argument, quote ID, price-lock or idempotency key.

The catalog price is indicative. Quote.expires_at is local freshness only.
Live quotes explicitly set final_charge_bounded=false. They cannot pass policy
validation. ensure_checkout_supported raises maximum_debit_unbounded, even with
the owner live flag enabled. The transport cannot dispatch buy-products.
Acknowledging uncertainty cannot override a hard cap. No final debit is guaranteed.
The adapter supports USD balance assessment, not live balance debit.

Owner checkpoint: existing owner-only execute route requires an authorized
request, matching preview fingerprint and confirm=true. The confirmation schema
also accepts acknowledge_uncertain_final_charge; it grants no bypass. Do not
enable live purchasing for this contract. A safe purchase requires a provider
maximum-debit guarantee (or separately reviewed payment contract that enforces
one), authoritative policy category metadata, and implementation/review of that
contract. Merely approving 55 cents does not constrain Bitrefill to 55 cents.

## Execution and reconciliation

Existing workflow uses SQLite BEGIN IMMEDIATE plus unique request/preview
execution constraints; the initiating claim commits before any potential write.
Policy, product, USD payment price, authorization and (for balance quotes) fresh
USD balance are checked before the claim. One durable record permits one attempt.
Every post-claim error freezes execution with reservations held. No checkout retry
exists. Revoke/cancel cannot release an unresolved execution's reservation.

Known invoice IDs reconcile through get-invoice-by-id, bound to the expected
product. Complete + delivered settles once; verified refund releases. Missing or
contradictory records retain funds. Slug and id are supported in nested product
identities. Unknown invoice IDs require manual account-history/provider review;
list-invoices is a supported read capability, but no automatic timestamp matching,
manual attachment, or force-release is provided. There is no reliable provider
request identifier for automatic reconciliation after an unknown debit.

Future within-policy agent checkout can use the same claim/policy boundary only
once a bounded provider contract exists. Agents must never receive credentials or
a direct buy-products capability. The first purchase retains owner confirmation.

## Review commands

```sh
cd ~/Projects/ZPermit/backend
.venv/bin/pytest -q
.venv/bin/python -m app.integrations.verify_bitrefill
```

The verifier uses only authenticated balance/search/details reads and prints
whitelisted summaries. It does not change gates, create invoices or spend funds.

## REST two-stage follow-up

See [REST assessment](bitrefill-rest-assessment.md) for authenticated personal
REST read verification and the separate invoice-create/pay contract review.
Two stages are documented, but USD sub-account selection, expiration and an
immutable final debit remain unverified. The MCP purchase blocker is unchanged.
No invoice-creation probe is permitted without the owner's separate approval.

## Current checkout recommendation

See [hackathon decision](bitrefill-checkout-recommendation.md). One unpaid REST
invoice was subsequently created with separate owner approval; that approval is
consumed. Existing invoice reads show BTC-labelled raw price 682, no verified USD
debit guarantee. MCP explicitly selects USD but has no verified max charge.
Quote bounds now default false; live checkout remains blocked.
