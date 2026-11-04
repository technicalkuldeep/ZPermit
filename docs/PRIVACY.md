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
