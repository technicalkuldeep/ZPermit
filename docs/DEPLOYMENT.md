# Public demo deployment: Render, one Docker web service

**Public HTTPS URL: NOT DEPLOYED / NOT VERIFIED.**

There is no connected Render/Railway authorization in this session. Docker is not
installed here, so the image has not been built locally. The frontend build and
the public ASGI entrypoint/policy isolation are tested separately. Do not expose
the private local app through a tunnel or deploy its .env/database.

## Exact Render steps

1. Review the Git exclusions and secret scan below; commit and push manually.
2. Sign in at https://dashboard.render.com and authorize GitHub access to
   https://github.com/technicalkuldeep/ZPermit.
3. Choose **New → Blueprint**, select **technicalkuldeep/ZPermit**, branch
   **main**, and use root **render.yaml**. Review/apply the Blueprint. It defines
   one free Docker web service, zpermit-demo. If the free plan is unavailable,
   choose an available plan only after reviewing its price yourself.
4. Root directory: repository root. Dockerfile: ./Dockerfile. No build/start
   override. Health check: /health. One instance, one worker. Automatic deploys
   are off; select a manual deploy if the initial deployment does not start.
5. The only application mode variable is ZPERMIT_PUBLIC_DEMO=true. PORT is supplied
   by Render. WEB_CONCURRENCY=1 is declared. **Do not add** Bitrefill keys,
   development owner/agent credentials, wallet files, viewing/spending keys,
   local database URLs, or an environment group containing those secrets.
6. Wait for the deployment to finish. Copy the **actual HTTPS URL** shown by
   Render. Do not guess a subdomain or submit a proposed URL as deployed.
7. Open the URL: choose **Start isolated demo**, create a permit (agent identity is
   fixed to demo-agent), search the sample Swiggy catalog, propose/approve a
   request, and inspect the blocked readiness. Confirm the persistent sample-data
   banner. A second private browser window must have its own empty workspace.
8. Verify these URLs before filling the submission deployment field:

```bash
# Set this to the actual URL copied from Render; it is not a suggested domain.
export DEMO_URL='https://YOUR-ACTUAL-RENDER-URL'
curl --fail --silent --show-error "$DEMO_URL/health"
curl --fail --silent --show-error "$DEMO_URL/api/mode"
curl --fail --silent --show-error "$DEMO_URL/permits" -o /dev/null
# Must return 401 without a demo session, never private account information:
curl --silent --output /dev/null --write-out '%{http_code}\n' "$DEMO_URL/api/workspace"
curl --silent --output /dev/null --write-out '%{http_code}\n' "$DEMO_URL/api/bitrefill/balance"
```

Expected mode is public_demo, sample_data=true, can_spend=false. Health must be
200; anonymous protected requests must be 401. Static assets and refreshed SPA
paths must load. Only then replace the placeholder in README/SUBMISSION with the
verified URL. Free services may sleep; this is a demo, not a payment service.

## Safety and persistence

- Each visitor gets random in-memory owner/agent capabilities and a new temporary
  SQLite database. The existing spending engine, authentication and concurrency
  checks still run. Public session capabilities do not grant any real account
  authority and are not the local development secrets.
- Sessions last 30 minutes, expire on restart, and are isolated from each other.
  Expired databases are deleted on subsequent API activity or shutdown. Do not
  enter personal information. There is no persistent user-data disk.
- Sample catalog is explicitly labelled. No fake paid invoice, delivered product,
  wallet balance, recipient or txid is seeded. Real account/invoice/execution and
  all Zcash routes are blocked. Use the private local app for the real phone flow.
- Limits: 16 KiB request bodies, 100 active sessions, 12 new sessions per client
  address per 10 minutes, 120 API calls per address/minute, 90/session/minute,
  300 API calls globally/minute, and 64 concurrent Uvicorn connections. Proxy
  clients may share an address and hit a shared limit. No forwarded IP header is
  trusted for bypassing limits. Single process/instance only; limits are not a
  production distributed quota/authentication system.
- Startup refuses configured private credential environment variables. The image
  copies application source and compiled assets only, not .env, SQLite, wallet
  artifacts, account experiment records, .git or caches. The public entrypoint
  does not load the local .env file.

## Local demo check without Docker

Run in a fresh shell without exported private account credentials. Keep your
existing private app on port 8000; demo uses port 8001. Do not source backend/.env.

```bash
cd ~/Projects/ZPermit/frontend
npm ci
npm run build
cd ../backend
ZPERMIT_PUBLIC_DEMO=true .venv/bin/uvicorn app.public_demo:create_demo_app --factory --host 127.0.0.1 --port 8001 --workers 1 --no-access-log
```

Open http://127.0.0.1:8001. A Docker-capable machine can instead run:

```bash
cd ~/Projects/ZPermit
docker build -t zpermit-demo .
docker run --rm -p 8001:10000 zpermit-demo
```

Do not pass --env-file, host directories or wallet/database volumes.

Official deployment references: [Render Docker](https://render.com/docs/docker),
[Blueprint fields](https://render.com/docs/blueprint-spec). Hosting account login
and GitHub authorization are the remaining deployment boundary.
