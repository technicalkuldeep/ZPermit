# Hackathon checkout decision — 2026-11-04

## Recommendation

Use the official hosted MCP USD balance route as the single target integration:
agent proposal -> ZPermit permit/reservation -> owner authorization -> server-held
one-shot execution claim -> buy-products(payment_method=balance,
balance_currency=USD) -> invoice reconciliation. Keep it **disabled** until the
provider supplies a charge-bound contract compatible with the authorized USD
reservation. No currently verified account-balance route meets all those
requirements. Owner risk acknowledgement or a larger local safety buffer cannot
make an unbounded debit satisfy a hard cap.

Do not pay the existing BTC invoice to test USD conversion. Do not create another
invoice. Do not reinterpret its raw amount, top up BTC, change the primary account
currency or substitute a payment method without a separately reviewed contract.
For the hackathon, be candid that purchase execution is blocked by the provider
contract; an unpaid invoice is a real invoice but not a paid/delivered purchase.

## Live read evidence

[Sanitized schema and read snapshot](experiments/swiggy-inr50-contract-read-2026-11-04.json).
Original creation authorization was consumed by exactly one earlier creation:
[original record](experiments/swiggy-inr50-unpaid-2026-11-04.json).
This follow-up made no new invoice, payment or buy-products call.

- Invoice 1f81dedb-ea5d-4065-9332-81d573e98f3a still exists.
- REST: invoice.status=not_delivered, payment.method=balance,
  payment.price=682, payment.currency=BTC, payment.status=unpaid.
- One matching order: Swiggy Money India, INR 50, status=created.
- MCP: invoice_status=unpaid, payment_info.method=balance/status=unpaid.
- USD balance before/after reads: 2500 cents; unchanged.
- Swiggy INR 50: in stock, USD catalog price 55 cents, accepts balance.
- Product type remains absent; do not infer an approved category from its name.
- Live-purchase gate remains false; both transport and policy block purchases.

## BTC units: no field-specific verification

Reviewed official REST invoice creation/pay OpenAPI, core concepts, crypto-payment
guide, the public reference MCP types, official CLI README, and searches of the
official documentation. The v2 Invoice.payment.price schema says number and gives
an example, but supplies no base-unit/decimal definition for BTC. The official
CLI describes satoshiPrice for Bitcoin payment details; older Thor API examples
also explicitly name satoshiPrice. Those are different fields/contracts and do
not establish the unit of v2 payment.price for this balance invoice.

Therefore 682 remains **raw/unverified**. No BTC or USD conversion is performed.
Even a future confirmation that it means satoshis would not fix an immutable USD
debit or authorize using the separate USD sub-account.

## Route comparison and financial exposure

| Issue | Existing REST invoice -> /pay | Hosted MCP buy-products, USD balance |
| --- | --- | --- |
| Uses existing invoice | Yes | No; creates a new purchase/invoice |
| Currency selection | Existing invoice says BTC; no verified USD selector on /pay | Explicit balance_currency=USD selects one sub-account |
| USD funds usable | Not established; primary REST balance previously 0 BTC | Documented balance option; USD spendable credit verified |
| Amount before debit | Raw 682 BTC-labelled units, units not verified | Catalog USD 0.55 indicative only |
| Final USD max | No fixed conversion, fee-inclusive charge or max verified | No max-debit argument, quote ID or price-lock verified |
| Prepayment control | Separate /pay delays debit, but cannot bind a max in its body | Balance buy-products auto-debits; return_payment_link does not defer it |
| Product prepayment forms | Not applicable to this gift card | submit-prepayment-step gathers bill/prepaid-card form data; not a spending cap or buyer final-price approval |
| Timeout/unknown outcome | Freeze known invoice; read/reconcile; no second pay | Freeze claimed execution and reservation; reconcile; no second buy |
| Duplicate attempts | /pay 404 means missing OR already paid; not proof no debit | Explicit idempotentHint=false: a second call can buy and debit again |

REST could require BTC funds, reject insufficient BTC, or have undocumented
conversion behavior. Do not assume which without provider confirmation. Neither
raw amount nor prior unpaid price stability establishes USD exposure.

MCP avoids the sub-account ambiguity but does not establish a 55-cent ceiling.
The current funded USD sub-account holds $25.00; do not represent that balance as
a contractual maximum debit, overdraft prohibition, or per-purchase limit.
A 55-cent reservation is ZPermit's accounting constraint, not a provider debit
constraint. A repeat purchase might add another full charge (at current indicative
pricing, two purchases would be approximately $1.10); no retry is authorized.
Delivery failure/partial delivery is not evidence of refund; preserve reservations
until authoritative payment/delivery/refund reconciliation.

## Minimal changes prepared

- Existing REST verifier can GET an existing invoice UUID and returns only its
  identity/status/product/payment projection. It labels raw amounts unverified,
  returns no USD conversion/Quote, never settles funds, and rejects /pay and
  arbitrary paths before transport. No new API route exposes provider payment.
- Quote.final_charge_bounded defaults false; server-domain test doubles explicitly
  assert their simulated guarantee. Live quotes remain unbounded and blocked.
- Existing permits, policy validation, owner confirmation, unique durable claims,
  transaction protection and reservation/refund rules are unchanged.
- No live write adapter, bypass flag, uncertainty override or payment retry added.

## Information required before a first real purchase

1. Provider documentation or a written Bitrefill confirmation identifying a
   supported mechanism that constrains the fee-inclusive debit to an authorized
   integer USD-cent maximum, fixes its validity period/expiry behavior, selects
   only USD balance and cannot fall back or reprice beyond that bound. A support
   statement that prices are usually stable is insufficient. No support message
   has been sent on the owner's behalf.
2. The ZPermit permit/request to use, its authorized USD-cent ceiling, and trusted
   product/category approval for Swiggy INR 50 x1. Missing category must be
   resolved explicitly, not invented from catalog categories or merchant names.
3. After the contract is implemented and tested, a separate owner approval for
   exactly one MCP USD balance attempt, with delivery to a private owner channel
   and no automatic retry. This would create a new invoice; the earlier approval
   covered only one unpaid REST invoice and cannot be reused.

Supplying a ceiling or accepting price risk alone cannot resolve item 1. If
Bitrefill cannot provide it, keep ZPermit live checkout blocked. A human purchase
outside ZPermit must not be presented as agent-executed hard-cap enforcement.

## Sources

- https://docs.bitrefill.com/docs/mcp-partner-integration-guide
- https://docs.bitrefill.com/docs/ecommerce-mcp
- https://docs.bitrefill.com/reference/post_invoices
- https://docs.bitrefill.com/reference/post_invoices-id-pay
- https://docs.bitrefill.com/docs/core-concepts
- https://docs.bitrefill.com/docs/crypto-payments
- https://github.com/bitrefill/bitrefill-mcp-server/blob/master/src/types/api.ts
- https://github.com/bitrefill/cli/blob/master/README.md
- https://github.com/bitrefill/thor-api-doc/blob/master/README.md (older API only)
- Authenticated tools/list schema saved in the read snapshot above.

## Review commands

```sh
cd ~/Projects/ZPermit/backend
.venv/bin/pytest -q
.venv/bin/python -m app.integrations.verify_bitrefill_rest --invoice-id 1f81dedb-ea5d-4065-9332-81d573e98f3a
```
