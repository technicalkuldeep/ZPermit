# Milestone 4: local NU7 testnet integration

**Status: safe integration boundary implemented; real wallet execution unverified.**
No real transaction ID has been produced. See the
[compatibility report](zcash-compatibility.md) for dated primary sources and local
checks. Unit fixtures are synthetic and are never submission evidence.

## Prefer the existing Zingo/public lightwallet path first

The [Zingo reuse and public-service guide](zingo-public-testnet.md) is the current
preferred route. Real read-only NU7/Ironwood connectivity and transaction lookup
work without a full node, and GUI signing avoids opening private wallet files.
The owner uses an existing funded Zingo Mobile wallet on a phone. No desktop
installation/search or new wallet is required; the phone approves and signs.
Do not install or sync Zebra merely to use that path. This document preserves the
existing **optional Zallet** integration; none of its approval, durable claim or
uncertainty protections has been replaced.

## Optional Zallet setup with a mentor

1. Obtain the hackathon's actual developer-resource packet; its URL was not in
   this repository or the public event description. Have the mentor confirm the
   release pair below and provide public-testnet Ironwood funds, not mainnet ZEC.
2. Install Zallet `v0.1.0-beta.4` (launcher and `zallet-zebra` together) and Zebra
   `v7.0.0` with its **indexer** feature. Use the release's signed/provenance-checked
   Linux amd64 artifacts or the documented source install commands below. No
   binary or service has been installed by this milestone. Source builds may take
   substantial time and disk space; install prerequisites from the projects'
   official guides. Avoid unpinned latest versions.

   ```bash
   cargo install --locked --git https://github.com/ZcashFoundation/zebra.git --tag v7.0.0 zebrad --features indexer
   cargo install --locked --git https://github.com/zcash/zallet.git --tag v0.1.0-beta.4 zallet-zebra --features rpc-cli
   cargo install --locked --git https://github.com/zcash/zallet.git --tag v0.1.0-beta.4 zallet
   ```

   Artifact verification caveat: beta.4 was re-released from a release branch.
   Follow [its release verification instructions](https://github.com/zcash/zallet/releases/tag/v0.1.0-beta.4),
   including the release-branch signing identity. Do not treat a filename as
   verification. The adapter uses an absolute executable path; Cargo normally
   installs into `~/.cargo/bin`, not `/usr/local/bin`.
3. Create separate private directories for a **dedicated testnet wallet** and
   Zebra state, outside this repository. Restrict wallet directory permissions to
   `0700`. Configure Zebra for public `Testnet`, JSON-RPC on `127.0.0.1:18232`,
   indexer gRPC on `127.0.0.1:18230`, and a dedicated state cache directory. Use
   the generated config for the pinned release, with these entries:

   ```toml
   [network]
   network = "Testnet"
   [state]
   cache_dir = "/absolute/path/to/zebra-testnet-state"
   [rpc]
   listen_addr = "127.0.0.1:18232"
   indexer_listen_addr = "127.0.0.1:18230"
   ```

   Do not add custom consensus overrides. Start the node using its documented
   `zebrad -c /absolute/path/to/zebrad.toml start` command and let it fully sync.
   Check disk capacity with the mentor first. Zallet must read the same machine's
   Zebra state, using matching v29 libraries; a remote Zebra URL alone is
   insufficient.
4. Create `/absolute/path/to/wallet/zallet.toml`, adapting the official beta.4
   configuration template. The relevant settings are:

   ```toml
   backend = "zebra"
   [builder.limits]
   [consensus]
   network = "test"
   [database]
   [external]
   broadcast = false
   [features]
   as_of_version = "0.0.0"
   [features.deprecated]
   [features.experimental]
   [indexer]
   validator_address = "127.0.0.1:18232"
   [indexer.read_state_service]
   grpc_address = "127.0.0.1:18230"
   zebra_state_path = "/absolute/path/to/zebra-testnet-state"
   [keystore]
   [note_management]
   [rpc]
   bind = ["127.0.0.1:28232"]
   ```

   The adapter refuses any `[consensus]` setting other than `network="test"`, and
   refuses non-loopback RPC bindings. Zebra read calls use no HTTP authentication;
   keep its RPC loopback-only. Zallet RPC uses its local cookie automatically.
   Keep the `.cookie` private: it grants wallet spending authority. Use absolute
   config/datadir paths consistently. Run locally as the wallet's trusted user.
5. Initialize encryption, generate a **new testnet-only** mnemonic and back it up
   locally using Zallet's own interactive commands. Never paste it into ZPermit,
   curl, source files, screenshots or an AI conversation. These commands must be
   run by the owner on the local terminal, not through this API:

   ```bash
   zallet --datadir /absolute/path/to/wallet generate-encryption-identity -p
   zallet --datadir /absolute/path/to/wallet init-wallet-encryption
   zallet --datadir /absolute/path/to/wallet generate-mnemonic
   zallet --datadir /absolute/path/to/wallet confirm-backup
   zallet --datadir /absolute/path/to/wallet start
   ```

   Consult `zallet confirm-backup --help` for the seed fingerprint/interactive
   backup flow of the installed release. Unlock a locked keystore locally via
   Zallet, using its documented secret-input mechanism; ZPermit has no unlock,
   key-import, seed-import or export route. A readiness `locked` field refers to
   sync state, not proof that an encrypted keystore is unlocked.
6. In a separate terminal, use these documented RPCs with the same datadir:

   ```bash
   zallet --datadir /absolute/path/to/wallet rpc getwalletstatus
   zallet --datadir /absolute/path/to/wallet rpc z_getnewaccount '"zpermit-testnet"'
   zallet --datadir /absolute/path/to/wallet rpc z_getaddressforaccount '"<account-uuid>"'
   ```

   Record the account UUID and testnet UA. Ask the mentor/faucet for Ironwood
   test notes at that UA and wait at least 10 confirmations. Sapling-only funds,
   transparent funds and legacy Orchard funds needing migration will not satisfy
   this integration's FullPrivacy payment policy. Create a second testnet UA for
   the recipient (a separate account is useful for a demonstration).
7. Set the `ZPERMIT_ZCASH_*` variables in `backend/.env` using `.env.example`:
   `ENABLED=true`, absolute `ZALLET_BINARY`, `ZALLET_CONFIG`, `ZALLET_DATADIR`,
   `ACCOUNT_ID`, `SOURCE_ADDRESS` (the original UA returned for that account), `ZEBRA_RPC_URL=http://127.0.0.1:18232`.
   Keep `LIVE_BROADCAST_ENABLED=false`. Network is fixed to `test`; any other
   value is rejected. Timeout defaults to 15 seconds (0.1–60); approval lifetime
   defaults to 300 seconds (1–900). Restart the backend after changes.
8. Run `python -m app.core.init_db` from `backend/` to add the independent payment
   table. It does not modify permit or Bitrefill tables. Then run the read-only
   verification command with your venv active:

   ```bash
   python -m app.integrations.verify_zcash
   ZPERMIT_RUN_LIVE_TESTNET_READS=1 python -m pytest -q tests/test_zcash_live.py
   ```

   Both require a configured, synced wallet; the live test also requires funded
   shielded balance. The default test suite skips this live test. It **never
   broadcasts**, even when the backend broadcast flag is true.

## Explicit owner payment workflow

All `/api/zcash` routes require the existing development **owner** bearer token.
Agents cannot use any of them. This is a separate owner-controlled TAZ demo,
not an agent spending capability, USD conversion, permit settlement or Bitrefill
payment rail. Existing authorization and reservation policies remain in force.

| Route | Behavior |
| --- | --- |
| `GET /api/zcash/readiness` | Checks local testnet config, node branch/height, wallet sync, matching tips and source account ownership |
| `GET /api/zcash/balance` | Reads Sapling/Orchard/Ironwood spendable zatoshis at 10 confirmations |
| `POST /api/zcash/payment-requests` | Validates UAs with Zallet; persists an approval-required request; no signing |
| `GET /api/zcash/payment-requests/{id}` | Reads the durable local payment record |
| `POST /api/zcash/payment-requests/{id}/confirm` | Exact owner confirmation; only dispatch path |
| `GET /api/zcash/payment-requests/{id}/evidence` | Reads canonical mined Ironwood transaction evidence from local Zebra |
| `POST /api/zcash/payment-requests/{id}/refresh` | Reads async operation / transaction status; never dispatches |

Preparation input:

```json
{"request_key":"owner-demo-1","destination":"<real testnet UA>","amount_zatoshis":100000}
```

Only integer zatoshis, 1 through 100,000,000 (1 TAZ), are supported. 100,000
zatoshis is 0.001 testnet ZEC. The amount excludes the wallet's automatic ZIP317
fee. This is an **approval-required request**, not a serialized unsigned
transaction or a fee-capped quote. Review the normalized Orchard-only source and
destination, amount, expiry and fingerprint returned by preparation. Other UA
receivers are stripped to prevent transparent or Sapling fallback. Normalization
may change the displayed address while retaining the intended Orchard receiver.

Confirmation body must include the returned fingerprint and the exact text:

```json
{"fingerprint":"<returned 64 hex fingerprint>","confirmation":"SEND TESTNET TAZ WITH AUTOMATIC ZIP317 FEE"}
```

Before deliberately confirming, change the wallet's `[external] broadcast` to
`true`, restart it, verify sync again, and set backend
`ZPERMIT_ZCASH_LIVE_BROADCAST_ENABLED=true` and restart the API. These flags do not
approve anything themselves. Preparation expires after five minutes by default;
create a fresh request if it expired. Never enable mainnet or relax FullPrivacy.

For a trusted local owner terminal, the equivalent opt-in workflow is:

```bash
python -m app.integrations.verify_zcash --prepare '<real testnet UA>' --amount-zatoshis 100000
python -m app.integrations.verify_zcash --confirm-payment '<returned payment UUID>'
python -m app.integrations.verify_zcash --payment '<same payment UUID>'
python -m app.integrations.verify_zcash --evidence-payment '<same payment UUID>'
```

The second command displays the stored details and requires the owner to type the
exact confirmation in an interactive terminal. It uses the local database/wallet
as a trusted owner utility; do not expose this command as an agent tool. The third
command is read-only reconciliation and may be repeated. No actual command above
was executed against a funded wallet during implementation.

## Persistence, uncertainty and evidence

A unique `(owner, request_key)` makes identical preparation idempotent; changed
normalized terms conflict. Fingerprints bind network, source, recipient, amount,
account, wallet paths, FullPrivacy and automatic fee policy. Owner confirmation
rechecks expiry, wallet configuration, NU7 branch and synchronization. SQLite
`BEGIN IMMEDIATE` serializes competing confirmations. Before any send, the backend
commits `initiating`. It then calls documented `z_sendmany` **once**, with minconf
10, null fee, and explicit FullPrivacy. Exact Decimal formatting avoids binary
floating-point amounts in CLI JSON. No secrets are passed in argv or environment.

A returned operation ID is persisted as `submitted`. Refresh uses
`z_getoperationstatus`, never the consuming `z_getoperationresult`. Success requires
one genuine returned txid and the explicit boolean `broadcast` field; otherwise
it remains uncertain. `broadcast=false` becomes `not_broadcast`, preserving its
real built txid without claiming submission. `broadcast=true` records wallet
submission, **not confirmation**. `z_viewtransaction` supplies confirmations and
status, including reorg decreases and expiry. A subsequent read failure preserves
the known txid. No API accepts a caller-supplied txid as proof of payment.

Timeout, malformed send output, failed persistence after dispatch, or a crash may
mean the daemon accepted the send. `initiating` and `uncertain` never dispatch
again. Repeating confirmation reads existing state. The wallet's operation IDs
are memory-only and may vanish after restart. Use read-only refresh; if no opid or
result survives, ask the mentor to inspect `z_listtransactions` / `z_viewtransaction`
and node history. **Do not create another payment or resend blindly.** No automated
lost-operation matching, repair, or rebroadcast is implemented. Even a failed
operation is never retried by this workflow.

For hackathon evidence, collect the real payment UUID, wallet-returned txid,
`broadcast=true`, wallet confirmation count/status, node testnet branch/height and
mined block hash. Independently inspect the full transaction with the synced
Zebra node's `getrawtransaction` (verbose `1`) / `decoderawtransaction` and verify
shielded actions, absence of transparent inputs/outputs, current NU7 chain and
canonical block inclusion. Confirm the pool is Ironwood; an `utest1` prefix or
64-character hex string alone is not evidence. Wallet `z_viewtransaction` only
shows spends/outputs visible to that wallet and cannot prove the absence of all
other transaction components. A public explorer is optional corroboration, not a
substitute for the node; looking up a txid may disclose your IP and interest.
The read-only `--evidence-payment` command (or evidence API route) automates the
public-shape check against the known stored txid: requires a mined v6 transaction
at/after NU7, nonempty Ironwood actions, empty transparent/Sprout/Sapling/old
Orchard components, positive confirmations and canonical blockhash by height.
Its schema is checked against [Zebra 7 transaction types](https://github.com/ZcashFoundation/zebra/blob/v7.0.0/zebra-rpc/src/methods/types/transaction.rs).
It returns a small public evidence summary rather than full wallet view output.
It fails closed before mining, after a reorg, or on unknown layouts. This trusts
the local full node's consensus validation; it does not decrypt hidden recipients
or independently verify cryptography in Python. It has only been tested with
synthetic node responses here. Preserve the node/wallet evidence locally and share only the intended
public submission fields. Do not include wallet secrets or private view output.

## Privacy and trust

Ironwood-to-Ironwood FullPrivacy transactions hide shielded sender/recipient
addresses, amounts and memos from ordinary public-chain observers. Transaction
IDs, block placement/timing, fees, shielded action counts and other public
metadata remain visible. Cross-pool migration amounts can be visible; this
adapter refuses to relax privacy to migrate funds. Correlation and endpoint
compromise remain possible.

ZPermit receives and persists the source address, normalized destination, amount,
owner identity, operation ID, txid and timestamps in its **unencrypted SQLite**
database. It knows the relationship between owner and payment. The wallet and
recipient know the details they can decrypt; a viewing-key holder may too. The
host/operator and a compromised API with wallet-cookie access can spend testnet
funds. Cookie access is powerful even though private keys stay inside Zallet.
Use a dedicated testnet-only wallet and protect filesystem access/backups. There
is no production authentication, encrypted database, hardware signing, HTTP seed
handling, or automatic wallet unlocking. RPC is local plaintext protected by
loopback and filesystem controls; it is not end-to-end anonymity. No parameters,
wallet stdout/stderr or secret material are deliberately logged by this adapter;
configure infrastructure/proxies to avoid request-body logging.

Testnet coins have no purchasing value. This milestone does not fund Bitrefill,
create invoices, deliver products, execute purchases, spend USD reservations or
mark requests fulfilled. Bitrefill remains blocked pending contract verification.

## Verification record / remaining blockers

- Verified from official releases and source: Linux toolchain choice, NU7 constants,
  address decoder, balance units/pools, FullPrivacy, async operation response and
  CLI string serialization. No Python Zcash cryptography dependencies added.
- Unit tests use clearly labeled in-process or subprocess/HTTP doubles. They test
  policy isolation, owner guards, exact confirmation, concurrency, uncertainty,
  persistence and contract parsing. They are not live transaction evidence.
- Live reads, address checksums with a real wallet, actual spendability, proving,
  broadcast and confirmations remain unverified until setup and funding above.
- Mentor assistance: actual hackathon links; verified build/artifact pair; enough
  node storage/sync time or a pre-synced local node; encrypted wallet initialization;
  Ironwood testnet funding and a recipient UA; deliberate owner confirmation;
  independent node inspection of the resulting genuine txid.

Final local validation (2026-11-04): **240 passed, 1 skipped**. This includes all
167 existing tests and 73 new unit-test cases; the skipped test is the explicit
live wallet read check. The existing FastAPI/Starlette TestClient deprecation
warning remains. FastAPI TestClient stalled at thread startup under the sandbox;
the successful full suite ran with sandbox escalation while unit wallet/network
calls remained explicitly blocked. `git diff --check` passed. The read-only
verification CLI exited with `wallet_not_configured`, as expected locally. No
broadcast, purchase, seed generation, git staging, commit or push was performed.
