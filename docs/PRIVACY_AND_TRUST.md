# Privacy and trust

ZPermit is a local-development application, not a hosted financial account or
production identity system. Two independent development credentials separate
owner actions from agent proposals. The browser retains those credentials in tab
memory only, so reload/disconnect requires reconnection. Use the local app on a
trusted computer, bind FastAPI to loopback, and keep backend/.env private.

The Bitrefill API key stays on the backend and is sent only in Authorization
headers. It is never a browser build variable, agent task input or QR payload.
Public invoice responses are projections without provider access tokens, email,
gift-card codes or redemption material. Reading an invoice does not attach it to
a permit, charge an account or settle a reservation.

Zingo Mobile owns phone signing, fee calculation, approval and broadcast. ZPermit
never receives a seed, spending key or viewing key. It cannot verify the owner's
shielded wallet balance. ZIP-321 requests contain a recipient, amount and optional
memo in readable form; base64url memo encoding is not encryption. These request
terms are stored in the local SQLite database. Keep request links/QRs private and
do not put secrets in memos. Revoking a USD permit does not revoke an external
phone-wallet URI or prevent a person sending it twice.

Zcash public observations use a trusted remote lightwallet service. Lookups
reveal IP/transaction interest. The existing decoder validates testnet/NU7 and
checks public transaction identity and reported block inclusion, but it is not
independent full-node consensus verification. Confirmation evidence does not
prove the private recipient, amount, memo, sender or ownership. Stale/failed
checks remain visibly distinct from current evidence. An owner-reported link
between a request and a txid is not a private receipt and cannot settle USD spend.

No analytics, third-party QR renderer, external font service, browser provider
key, automatic payment retry, or phone-wallet control is added by the frontend.
SQLite is not encrypted by the application. Production needs real identity,
TLS, managed secrets, appropriate access controls and a reviewed threat model.


## Shielded transaction claims

Shielded transactions conceal shielded sender/recipient addresses and amounts
from ordinary public observers; the encrypted memo is not revealed by a public
transaction lookup. This is not a claim that every use of a unified address is
shielded: review the actual Ironwood pool selection and transparent components
in the phone and evidence. Public txids, timing, block heights, confirmations,
transaction structure and other public metadata remain visible. ZPermit cannot
recover a shielded sender, recipient or amount from a txid alone. A viewing key
would change the trust/privacy boundary and is not requested or published.

## Public demo boundary

The public service uses a separate entrypoint and fresh temporary databases for
each visitor. It receives no real Bitrefill key, local development credentials,
wallet keys or private user records. Random demo capabilities grant authority
only over that visitor's disposable policy records. The existing owner/agent
checks and budget engine are reused, not disabled. Sessions expire in 30 minutes;
restarts delete demo data. Do not enter private information.

A persistent banner identifies sample/demo data. No paid invoice, delivered
product, real wallet balance, destination or txid is seeded. Account/invoice,
wallet, payment and broadcast endpoints are denied. The server refuses configured
private credential environment variables. Request/session/body/concurrency limits
are demo abuse controls, not production multi-user authentication or guaranteed
DDoS protection. Hosting may still record request IP/time; access logs are disabled
by this application entrypoint, but provider infrastructure is separately trusted.

Bitrefill is trusted for account data, product availability and invoice states.
Without a bounded-charge contract, even owner approval cannot turn a catalog
price into an enforceable debit cap. Local Zingo signing/fees remain under the
owner's explicit phone approval. Testnet ZEC/TAZ and Bitrefill USD store credit
are separate funds; neither automatically funds or settles the other flow.
