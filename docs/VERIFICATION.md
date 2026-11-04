# Application verification

## Automated checks

- Frontend TypeScript and Vite production build: passed.
- Frontend Vitest / Testing Library: 23 passed. Covers strict money parsing,
  credential destination/role separation, no automatic network retry, deterministic
  discovery, INR/USD proposal separation, denied-request stopping, unpaid invoice
  rendering, authenticated QR blob loading/cleanup, manual-send guidance, and
  stale public-evidence/privacy claims.
- Backend suite: 356 passed, 2 skipped. One existing FastAPI/TestClient
  deprecation warning remains. External calls are mocked; the two existing
  opt-in live tests remain skipped.
- `git diff --check`: passed.

Frontend fixtures are isolated test doubles and never appear in the application
as seed data. Invalid test-only addresses/txid labels are deliberately not usable
for a live send/lookup. No live recipient or transaction ID is invented.

## Browser limitation

Chromium is installed, but headless launch fails because libnspr4.so is absent.
No further browser download or system dependency installation was performed after
this limitation was identified. `npm run test:browser` retains the integration
specifications for a machine with working browser libraries. Browser visual and
responsive rendering checks are therefore not claimed as passed here.

The browser suite starts the real FastAPI application and uses temporary SQLite
records and random development credentials. It does not touch the user's normal
database. The provider-read case is opt-in:

```bash
cd ~/Projects/ZPermit/frontend
ZPERMIT_BROWSER_LIVE_READS=1 npm run test:browser
```

It performs only catalog/balance/existing-invoice reads and local proposals;
no invoice creation, buy-products, payment or broadcast is dispatched.

## API-level integration

An isolated temporary database is used for real policy routes: create/view a
permit, submit pending approval, approve and reserve, deny an excessive request,
revoke and release the unexecuted reservation. The built frontend app shell is
served on the FastAPI origin. Unknown API routes retain 404 behavior.

Real authenticated Bitrefill reads check Swiggy discovery/details, current USD
balance, blocked readiness and the existing unpaid invoice. Public NU7 readiness
is checked independently. Live payment request terms and a real wallet txid remain
user-entered interface inputs; no wallet send or live phone evidence is invented.
The backend's existing QR/ZIP-321 and evidence tests cover those mechanics, and
frontend tests cover their display and authenticated image retrieval.

No financial gate was relaxed, no invoice was created, no credit spent, no wallet
broadcast performed, and no git staging, commit or push was run.

## Final authenticated read result

The isolated API smoke run returned HTTP 200 for real Swiggy discovery/details,
USD balance and the existing invoice. The INR 50 package had an indicative payment
price of 55 USD cents; spendable account credit was 2500 USD cents. Invoice
1f81dedb-ea5d-4065-9332-81d573e98f3a remained unpaid, with raw price 682 and currency
BTC. No conversion of that raw price was attempted. Preparation returned HTTP 201
with state=blocked and blocker=maximum_debit_unbounded. NU7 public readiness was
HTTP 200, ready=true, branch 77190ad9. These are live read observations, not a paid
purchase or phone-wallet transfer.

The production shell, health, create/view/approve/reserve/deny/revoke routes all
passed against the actual FastAPI app and temporary SQLite database. The final
frontend source/assets were checked for the configured provider and development
credentials; none were found. No overlapping editor/installer processes remained.

## Final deployment pass

- Fixed agent selection/input to match the authenticated server identity; no
  authentication or ownership checks bypassed. Existing incompatible permits are
  preserved and excluded from that agent's task selector.
- Frontend TypeScript/Vite build: passed; frontend tests: 24 passed.
- Backend tests: 366 passed, 2 skipped; one existing TestClient deprecation warning.
- Deadline critical selection: 88 passed (policy, workspace and public isolation).
- Real local Uvicorn public-demo smoke: health, static app, refreshed SPA paths,
  fresh session, create/propose/approve/deny/blocked-readiness all passed. Anonymous
  workspace/account access returned 401; authenticated demo real account/wallet/
  execution routes returned 403. No provider writes or broadcasts occurred.
- Git private-file exclusions and configured-secret scan passed. No staging,
  commits or pushes performed.
- Docker is unavailable locally; image build must be verified by the hosting
  builder. No Render/Railway account authorization is connected. No public HTTPS
  deployment is claimed. Follow docs/DEPLOYMENT.md and verify the actual URL.
- Public sessions/catalogue are explicitly sample-only and isolated. They do not
  contain the private account balance, unpaid invoice, wallet or phone evidence.
