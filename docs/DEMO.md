# Three-minute demo

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
