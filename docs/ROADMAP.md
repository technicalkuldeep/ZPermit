# Thirty-day development roadmap

| Days | Deliverable | Acceptance criterion |
| --- | --- | --- |
| 1–5 | Provider contract resolution | Written, field-specific USD units, fee inclusion, sub-account selection, expiry and maximum-debit semantics. Stay blocked if absent. |
| 6–10 | Bounded checkout adapter, only if the contract supports it | Transactional one-shot claims, no blind retries, uncertain-result reconciliation, owner-reviewed first purchase, preserved reservations. |
| 11–15 | Production identity and trust review | Separate owner/agent sessions, secure deployment design, scoped secrets, threat model and data-retention controls. |
| 16–20 | Phone integration validation | Test installed Zingo versions on real phones; verify QR/link fields, manual fallback and honest private-evidence limits. |
| 21–25 | Product reliability | Pagination for workspace history, better task scope, private delivery channel, accessibility and browser/device QA. |
| 26–30 | Audited demonstration and release | Repeatable end-to-end demo with genuine evidence, real owner approval, documented limits and independent security review. |

Payments remain gated by provider guarantees, not calendar dates. New agent
capabilities must not inherit unrestricted provider credentials or wallet keys.
