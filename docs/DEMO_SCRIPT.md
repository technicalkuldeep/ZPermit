# ZPermit — 2–3 minute submission presentation

Choose the public isolated sample demo for judges, or the private local app for
real authenticated reads. State which one is on screen. A public demo never
shows the funded account or an own-wallet transaction. No paid purchase or send
is part of this script without a separate genuine owner action.


Use real local records; start with an empty workspace if none exist. Do not seed
fake purchases or txids. Keep credentials and the developer .env off screen.

**0:00–0:25 — The problem and connection**
“An agent can find things for me. It should not get my entire spending authority.
ZPermit gives it exact permissions and makes each decision inspectable.” Connect
using local owner/agent credentials. Explain that production authentication is
future work and the provider key stays on the backend.

**0:25–1:00 — A permit is a boundary**
Create an Everyday essentials permit: total $10, maximum $1 per purchase, merchant
swiggy-money-india, explicit proposal category gift_card, approval threshold $0,
and a future expiration. Show zero spend and no reservation before a request.

**1:00–1:40 — A real agent request, an honest blocker**
Run the ₹50 Swiggy task. It searches real Bitrefill products, fetches the
indicative USD price, and submits to the existing policy engine. Owner approves
the reservation. Show pending versus authorized and the reserved cents.
“The provider has no verified maximum-charge contract. So even an authorized
request cannot debit my account. Our UI refuses to call that a successful buy.”
Show the disabled checkout control. Do not enable purchasing for the demo.

**1:40–2:15 — Real account evidence**
Read the USD balance and existing unpaid invoice. Its INR 50 face value and
BTC-labelled raw price are separate from USD budget/credit. Explain that the
unpaid invoice was created in one earlier owner-approved experiment; no invoice
or payment is created by this screen. If an API is unavailable, show its error.

**2:15–2:50 — The phone owns the wallet**
Show Zcash Payments. Enter a real recipient and amount only if available; otherwise
show the empty input state. A generated QR is a request, not a payment. Explain
scanning/manual-copy fallback and explicit approval in Zingo on the phone.
If an existing genuine txid is available, verify it; otherwise leave the form
empty. Public confirmations cannot prove private payment details. Never paste a
fabricated ID or claim a live send occurred during UI testing.

**2:50–3:00 — Close on trust**
“Permission is not payment. A public txid is not a private receipt. We connect
working rails while keeping those boundaries explicit.” Show revocation or the
activity view. A future bounded Bitrefill contract can unlock one-shot execution
without weakening the permit engine.


## Exact owner phone steps (private local app only)

1. Open the existing funded Zingo Mobile wallet; confirm public Testnet,
   synchronization and NU7/Ironwood compatibility. Do not restore another wallet.
2. In the private ZPermit UI, Zcash Payments, paste the genuine intended recipient
   utest1 address. Enter a small native testnet amount, such as 0.001 TAZ if that
   is the amount you intend; optional memo must not contain secrets.
3. Generate the request on the computer. Scan its QR on your phone. If scan/link
   support is missing or drops fields, cancel that draft and manually copy the
   full address, native TAZ amount and memo into Zingo.
4. Compare full recipient, amount, memo, Testnet and shielded Ironwood selection.
   Review the wallet-calculated fee/total. Approve Send explicitly on the phone.
   ZPermit never approves, signs or broadcasts it.
5. If the result is uncertain, sync/check wallet history before doing anything
   else. Never resend blindly. Copy the genuine txid from history after sending.
6. Paste that txid into the existing ZPermit request's evidence form; verify and
   refresh confirmations. Public inclusion does not prove the private terms or
   settle a USD reservation. Put the actual txid in SUBMISSION only when genuine.

If the wallet/server/build cannot verify NU7 or Ironwood, stop; do not downgrade
networks, invent evidence or use an unrelated transaction as your own payment.
