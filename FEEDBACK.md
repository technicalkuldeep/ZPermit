# Actual Bitrefill and Zcash developer feedback

## What worked with Bitrefill

- Authenticated personal Bearer access succeeded against the hosted MCP and REST
  read APIs. Server-held keys worked without exposing them to a browser/agent.
- Authenticated MCP get-balances returned the USD sub-account's spendable balance
  of $25.00, with amount="25.00", amount_base=2500 and decimals=2.
- Real product discovery/details worked for Swiggy Money India, Flipkart India and
  Google Play India. Observed INR 50 denominations had indicative payment prices
  of USD 0.55, 0.56 and 0.57 respectively; these are observed prices, not promises.
- With explicit owner approval, exactly one REST balance invoice with
  auto_pay=false was genuinely created. It remained unpaid and the USD credit
  stayed unchanged. Creation was not mistaken for payment or product delivery.

## Friction encountered

1. Search exposed slug while details used id. Country was country_code rather
   than the earlier model's country, and product type was absent for the observed
   products. Normalization had to preserve unknown metadata rather than invent it.
2. Face value/denomination was INR while the catalog payment price was USD.
   Budgeting must use the payment currency's integer cents, not INR face value.
3. REST invoice creation returned payment.price=682 and payment.currency=BTC,
   despite the separate funded USD sub-account. The examined v2 schema did not
   establish field-specific BTC units, USD selection/conversion or a fixed USD
   debit. REST primary balance reads returned zero BTC; that did not mean USD
   credit was absent. No raw amount was converted or treated as USD cents.
4. The authenticated MCP schema explicitly marked buy-products non-idempotent;
   balance checkout may debit immediately. No purchase retry is safe after an
   unknown result. We did not call buy-products or invoice /pay.
5. No verified maximum-debit argument, bound quote ID, price-lock/expiry or
   pre-debit final-price confirmation was established for this account-balance
   path. The bill-payment prepayment form flow is not a spending-cap control.
6. An autonomous agent with a hard USD cap therefore cannot safely turn a catalog
   quote into a debit, even when a human approves the quoted amount. ZPermit's
   checkout stays blocked rather than falsely claiming exact-price enforcement.

## Specific API improvements

- A create/preview quote with integer minor units, explicit payment/sub-account
  currency, fee-inclusive final total, expiration and authoritative product/type.
- A supported max_total_minor_units and expected_currency on execution, rejecting
  any excess or currency fallback atomically before debit.
- Quote-ID binding and a guarantee that pay-existing-invoice does not reprice,
  add fees or convert the charge outside the approved bound.
- Idempotency keys backed by durable execution records plus lookup by client
  request identifier after timeout, with explicit outcome-uncertain status.
- Consistent field/unit definitions across REST and MCP; documented duplicate-pay,
  expiry, refund and partial-delivery semantics with sanitized real response examples.

These requests arise from actual authenticated reads and the one unpaid invoice
experiment. No completed purchase, delivery or purchase-timeout experiment on the
live account is claimed. Timeout/concurrency tests use isolated test doubles.

## Zcash / wallet feedback

The existing ZIP-321 preparation and QR handoff fit a phone-owned wallet well.
NU7/Ironwood network readiness and public transaction observation are implemented,
but no confirmed transaction from our own phone wallet is available yet. Clear
installed-version compatibility guidance for unified addresses, Ironwood and
ZIP-321 scan/link fields would help. Public confirmations should be documented
separately from proof of shielded recipient/amount/memo/sender, which a public txid
lookup cannot provide. No seed, spending key or viewing key was imported.

## Deadline product status

The private local app retains real integrations. The public demo uses explicitly
labelled sample data, isolated temporary visitor records and no account/wallet
credentials. It is a policy demonstration, not a completed live payment.
