# Milestone 4 compatibility report — 2026-11-04

## Decision and local evidence

Ubuntu 24.04 x86_64; Python environment available. `command -v` found none of
`zallet`, `zebrad`, `zcash-cli`, `zcashd`, or `zingocli`. No wallet or funded
address has been supplied. **No live wallet, balance, broadcast, or transaction ID
is verified.** Zallet v0.1.0-beta.4 + co-located Zebra 7.0.0 is the selected documented Linux route,
not an installed or live-tested dependency. No Python Zcash cryptography library
is used. Installation and wallet funding remain blockers.

## Primary references checked

- [Zebra 7.0.0-rc.0 release](https://github.com/ZcashFoundation/zebra/releases/tag/v7.0.0-rc.0): NU7 public testnet activation 4,465,026, branch ID `0x77190AD9`;
  v29 state requires matching Zallet readers.
- [Zebra 7.0.0 release](https://github.com/ZcashFoundation/zebra/releases/tag/v7.0.0): stable NU7 support.
- [Zallet installation](https://zcash.github.io/zallet/guide/installation/index.html)
  and [Zallet Book](https://zcash.github.io/zallet/print.html): Linux support,
  co-located Zebra built with `indexer`, matching state formats, wallet RPCs.
- Exact RPC source reviewed at Zallet commit
  `b0034a0925fc0c12eb4cd619114c3287b160093f` (upstream main at research time).
  `getwalletstatus`, `z_getbalanceforaccount`, and `z_sendmany` implementations
  compared byte-for-byte against `v0.1.0-beta.4`: identical. Released CLI source
  checked too: string results (operation IDs) are printed **without JSON quotes**.
- [Zallet beta.4 release](https://github.com/zcash/zallet/releases/tag/v0.1.0-beta.4)
  explicitly follows NU7 and requires Zebra 7.0.0 or later. It was re-released from
  a release branch; follow that release's artifact verification instructions.
- [NU7 deployment ZIP 259](https://zips.z.cash/zip-0259) corroborates constants.
- [Official NU6.3 overview](https://z.cash/upgrade/nu6-3/) and
  [ZIP 2005](https://zips.z.cash/zip-2005): Ironwood uses Orchard receivers;
  older pool assumptions are unsafe.
- [Official NU7 overview](https://z.cash/upgrade/nu7/) still says activation
  unset; release-specific notes above are more current and concrete.
- [Official testnet guide](https://zcash.readthedocs.io/en/latest/rtd_pages/testnet_guide.html):
  test coins are distinct from valuable mainnet ZEC.
- [Hackathon event](https://luma.com/freesocietyhackathon) found; no hackathon
  developer-resource packet/link exists in this repository or the inspected public
  event description. Ask mentors for the actual packet and compare its pinned
  toolchain with this report before live use. Do not claim packet verification.

## Scope

Use a dedicated public-testnet wallet (`consensus.network = "test"`), never custom
network overrides, regtest or mainnet. Backend accepts only testnet Unified
Addresses (`utest1…`) containing an Orchard receiver, decoded by Zallet rather
than trusting the prefix. The supported payment pool is **Ironwood**, using the Orchard receiver in a
Unified Address. Orchard receiver type is not the old Orchard value pool.
Zallet reports Sapling, Orchard and Ironwood balances separately. Old Orchard funds
may require a migration with revealed cross-pool amounts; this adapter will not
relax privacy to do that. Obtain directly funded Ironwood test notes instead.
FullPrivacy forbids transparent inputs/outputs and
cross-pool amounts. Sapling, Sprout, transparent and TEX destinations are outside
this integration's supported address policy. Orchard receiver encoding does not
by itself prove the mined pool; wallet/node transaction inspection is required.

Zebra is a consensus node, not a wallet. lightwalletd is a lightwallet server, not
a key-holding wallet. Deprecated zcashd/zcash-cli and unverified consumer-wallet
NU7 support are not selected. The adapter calls only documented Zallet methods;
unknown response layouts fail closed. Async sends can succeed without broadcasting
when `external.broadcast` is false; check the explicit `broadcast` result field.
Operation IDs are memory-only: never consume results and never resend after loss.

Additional released contracts checked: `z_getaccount` / `list_accounts.rs` verify
that the original configured source UA belongs to the configured account UUID;
Zebra 7's `TransactionObject` distinguishes Ironwood from Orchard and exposes the
public transaction shape used by read-only evidence checks. These checks have
been exercised only with test doubles, not a running wallet/node.
