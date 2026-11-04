# Zingo Mobile signing + ZPermit public NU7 evidence

The owner has clarified that the existing wallet is **Zingo Mobile on a phone**
and already holds testnet tokens. That balance is owner-reported; the backend
cannot read a shielded balance without viewing authority and does not request it.
No desktop installation, new wallet, restore, seed import or full node is needed.
No more desktop searches are part of this workflow.

ZPermit prepares a request and QR; the phone owns approval, fee calculation,
signing and broadcasting. The existing protected public-testnet workflow verifies
the resulting txid. This never turns a USD permit into unrestricted wallet access.

## Verified contracts and limits

- [ZIP-321](https://zips.z.cash/zip-0321): one `zcash:` URI with the testnet address
  in the path and an exact decimal `amount`; an optional memo is UTF-8 encoded,
  then unpadded base64url. Memo input is limited to 512 UTF-8 bytes. No indexed
  recipients, custom assets, labels, messages or unknown required parameters.
- [Zingo Mobile](https://github.com/zingolabs/zingo-mobile) is an Android/iOS
  Zingolib wallet. The current source does not prove which build is installed on
  the owner's phone or which link fields its scanner/OS handoff will honor.
  `wallet_link_support` therefore stays `unverified_for_installed_version`.
- Existing official-library validation checks full UA checksum, testnet encoding
  and an Orchard receiver (used for Ironwood). It does not prove address ownership,
  funding or that the phone will select Ironwood rather than another UA receiver.
- Existing TLS gRPC reads at `https://testnet.zec.rocks:443` verify reported network,
  NU7 branch `77190ad9`, Ironwood support, transaction identity, block inclusion
  and confirmations. This trusts the remote service, not an independently synced
  full node. No public-client send RPC exists.

## Start the backend

From `backend/`:

```bash
source .venv/bin/activate
python -m pip install -e '.[dev]'
cargo build --locked --release --manifest-path tools/zcash-public-inspect/Cargo.toml
python -m app.core.init_db
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The existing Rust tool only decodes public addresses/transactions; it is not a
wallet. QR generation uses local `qrcode`/Pillow, with no third-party QR service.
Schema initialization adds `zcash_mobile_payment_requests` and
`zcash_mobile_payment_evidence`; existing Zallet/public evidence tables are not
altered. No migration of wallet files occurs.

Keep the existing distinct development owner/agent credentials configured. Set
`ZPERMIT_ZCASH_PUBLIC_READS_ENABLED=true` for evidence lookups and restart after
configuration changes. Preparation/QR generation only need the offline decoder;
they do not need a connected wallet, public RPC or the Zallet broadcast flag.

All routes below require the **owner** bearer credential. Use Swagger on the
computer at `http://127.0.0.1:8000/docs`, authorize with that credential, and use
the mobile routes. Do not expose the development API publicly or put its token
in a link/QR. The phone needs the `zcash:` payload, not API access.

## 1. Prepare a real request

Obtain the genuine recipient's `utest1…` receiving address. Confirm that the
existing phone wallet is on public Testnet and synchronized. There is no need to
request faucet funds if its existing Ironwood funds are already spendable.

`POST /api/zcash/mobile/payment-requests`:

```json
{
  "request_key": "phone-demo-1",
  "destination": "<replace with the real recipient utest1 address>",
  "amount_zatoshis": 100000,
  "memo": "ZPermit testnet demo"
}
```

The placeholder is intentionally invalid; replace it with a genuine address.
100,000 zatoshis is **0.001 TAZ**; accepted amounts are strict integers from 1 to
100,000,000 zatoshis (at most 1 TAZ). The requested amount excludes fees, which the
phone calculates. `memo` is optional; leave it out to omit the URI memo field.
The owner must provide the actual recipient/amount/memo before a real request
or QR artifact can be prepared for the demonstration.

The response includes stored immutable terms, `payment_uri`, `qr_path`,
`amount_taz`, and review/trust flags. The URI has this structure:

```text
zcash:<real utest1 address>?amount=0.001&memo=<unpadded base64url>
```

No binary float, exponent or nonstandard network parameter is used. Repeating
identical terms with the same owner/request key returns the same request. Changing
recipient, amount or memo under that key returns 409. Requests remain
`prepared_for_external_wallet`; they never become paid because an observation
exists. Only the original terms can be retrieved; there is no edit or send route.

## 2. Retrieve the payment QR

`GET /api/zcash/mobile/payment-requests/{id}` retrieves the request.
`GET /api/zcash/mobile/payment-requests/{id}/qr.png` returns its QR as a PNG with
`Cache-Control: no-store`. It encodes **only the exact ZIP-321 URI**: no token,
API URL, owner ID, seed or signing authority.

Use Swagger's authenticated request/download option, or save it with curl on the
computer using your existing owner credential variable:

```bash
curl --fail-with-body -sS \
  -H "Authorization: Bearer $OWNER_TOKEN" \
  "http://127.0.0.1:8000/api/zcash/mobile/payment-requests/$MOBILE_REQUEST_ID/qr.png" \
  --output /tmp/zpermit-phone-payment.png
```

Open the downloaded PNG on the computer yourself and scan it in Zingo Mobile.
Alternatively transfer the `payment_uri` to the phone and open it only if the
installed app/OS supports that scheme. No app-specific deep-link behavior is
assumed. The owner credential must never be sent to the phone as part of the QR.

## 3. Review and approve on the phone

1. Use the existing wallet; do not create/restore/import another one. Confirm
   Testnet, synchronization and available Ironwood funds in the app.
2. Scan/open the request. **Before approving**, compare the full recipient,
   exact TAZ amount and optional memo with the backend response. Check that the
   wallet is preparing an Ironwood shielded transfer. A UA/link does not enforce
   the selected pool or a privacy policy by itself.
3. If the installed scanner/link handler rejects the request or drops/misreads
   any field, cancel that draft. Manually copy the recipient, native TAZ amount
   and optional memo into Zingo Mobile instead; recheck every field. Do not use
   USD conversion or assume a missing memo was honored.
4. Review the wallet-calculated network fee and total debit. The backend request
   is not a final fee quote and grants no signing authority.
5. The owner explicitly approves using the phone's final Send/Confirm control.
   This is **phone-wallet-initiated**, never backend-initiated. Link/QR generation
   is not approval, broadcast, evidence of spendability or proof of payment.
6. Copy the genuine txid from the phone's transaction history. On a timeout or
   ambiguous result, synchronize and inspect history first. Do not scan/send
   again blindly. Request idempotency does not prevent a phone from sending the
   same URI twice; the URI has no remote revocation/expiry guarantee.

No real send has been performed by ZPermit or an automated test.

## 4. Submit the genuine txid through the existing evidence workflow

The existing `POST /api/zcash/public/transactions` still accepts:

```json
{"request_key":"phone-evidence-1","txid":"<replace with the actual 64-character lowercase hex txid>"}
```

For an explicit association with the saved phone request, submit the same body to
`POST /api/zcash/mobile/payment-requests/{id}/evidence`. This delegates to that
same protected verification/persistence service. An observation previously
registered at the public endpoint can be attached using its original request key
and txid. Identical retries are idempotent; a different txid for an already linked
phone request conflicts, and an observation cannot be linked to two phone requests.
No guessed txid, manual claim of confirmation or private payment proof is accepted.

The response contains the existing observation, an `owner_reported` association,
and permanently false flags for recipient, amount, memo and sender verification.
Follow its observation ID with the existing routes:

- `GET /api/zcash/public/transactions/{observation_id}`
- `POST /api/zcash/public/transactions/{observation_id}/refresh`

Refresh until the latest successful check reports mined status and confirmations.
An unsuccessful check preserves the earlier snapshot but sets
`last_check_succeeded=false`; do not present stale evidence as current.
Pending/off-chain results and reorg decreases remain distinct. These calls never
retry a wallet send or modify the existing Zallet durable-broadcast claims.

## What the evidence proves

The official decoder computes the txid from real fetched transaction bytes,
requires NU7 v6/Ironwood, and reports pool structure/transparent component counts.
For mined status the public client checks matching txid/Ironwood actions in the
reported block, agreement with tree state and confirmations relative to its tip.
The `trust` label remains `remote_lightwallet_server`; this is not local full-node
consensus/proof verification. For the shielded demo, inspect single-pool Ironwood
and zero transparent inputs/outputs, not merely an address prefix.

**A confirmed txid does not prove the private recipient, transferred amount,
memo, sender ownership or that this request was satisfied.** Associating a txid
is an owner's report, including when someone supplies an unrelated existing txid.
Compare actual payment details in the phone's final summary/history; the backend
cannot independently prove them from public chain data. No viewing key is
requested, and no purchase is automatically fulfilled or reservation released.

## Privacy and preservation

The prepared address, amount and plaintext memo are stored in SQLite and appear
in the URI/QR. Base64url is encoding, not encryption. Anyone with the file/link can
read those requested details, even though the eventual on-chain memo/payment is
shielded. Do not place secrets in the memo; keep QR artifacts private. Public
lookups reveal your IP/txid interest to the service. Transaction timing, action
counts, fees and other public metadata remain visible.

Existing spending permissions, budget reservations, merchant restrictions,
approvals, expiration/revocation, concurrency and Bitrefill controls are unchanged.
Agents cannot prepare phone requests, retrieve QRs or attach evidence. Existing
Zallet routes remain separate and are not used to control the phone wallet.

## Testing and live status

```bash
python -m pytest -q
ZPERMIT_RUN_PUBLIC_TESTNET_READS=1 python -m pytest -q tests/test_public_testnet_live.py
```

Unit interactions use clearly labeled doubles; PNG generation runs locally. Tests
never sign/send. The opt-in test performs real public-network reads only. Earlier
live checks verified NU7/Ironwood connectivity and an unrelated public transaction;
that probe is not the owner's payment or hackathon evidence. The owner's phone
balance is reported by the owner; actual recipient, requested terms and eventual
txid are still required to complete the real phone demonstration.

Phone-flow validation: **303 backend tests passed, 2 opt-in live tests skipped,
0 failures**. The existing FastAPI/TestClient deprecation warning remains. New
unit tests cover exact integer amount formatting, UTF-8 byte limits and base64url
memos, locally rendered PNG payloads, authentication/ownership, immutable request
idempotency/concurrency, existing evidence reuse, failed lookups, association
conflicts and preserving false private-detail verification after mined evidence.
All external interactions use test doubles in unit tests; no phone payment or
live txid submission was performed. `git diff --check` passed. No wallet creation,
restore/import, seed access, Bitrefill change, git staging/commit/push or send.
