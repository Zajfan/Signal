# Signal local development

Signal's local runtime uses Python and SQLite. It runs without cloud credentials or third-party Python packages. Node is only needed for the Worker checks and browser tests.

```bash
python3 backend/local_server.py
# Open http://127.0.0.1:8000
```

The local database is `signal.sqlite3` (ignored by Git). To isolate experiments:

```bash
python3 backend/local_server.py --db /tmp/signal-experiment.sqlite3 --port 8010
```

## Workspaces

- `/`: candidate search and saved jobs.
- `/jobs/{id}`: public detail page for an approved, unexpired job.
- `/employer`: employer dashboard, company profile, draft editor and preview.
- `/admin`: company verification and paid-post moderation.
- `/sources`: source health and imported-job review.

The development identity panel changes the local employer ID/email used by the browser. This is a testing convenience, not an account registration system. The local server binds only to loopback. The operations pages use the local moderator header; production requires real staff authorization.

## Employer walkthrough

1. Open `/employer`, then Company. Enter company name and HTTPS website and submit for verification.
2. Open `/admin` and verify the company.
3. Return to `/employer`. Create an AI-related role, enter location/country and application URL, and save a draft. Reopen it to edit or preview it.
4. Start simulated checkout, then complete the simulated payment. No money is charged.
5. Open `/admin` to review and approve the post.
6. Open `/` and follow the job's detail and application links.

Drafts, unpaid posts, rejected posts and expired posts are not publicly searchable. Draft editing stops when checkout begins. Changing the verified company profile starts a new verification review.

## Checks

```bash
npm install
npm test
npx playwright install chromium
npm run test:browser
```

The browser suite creates a disposable SQLite database and loopback server. It never seeds or clears `signal.sqlite3`.

## Runtime boundaries

The new workspaces and ingestion controls target the Python local runtime. `backend/worker.mjs` remains the separately tested Cloudflare/D1 production foundation. It does not yet expose every local route or serve this client. Do not deploy it unchanged expecting local identity controls, local moderation or simulated checkout to become production authentication/payment features.

Production release still requires trusted sign-in, company membership/roles, configured merchant prices, payment and refund reconciliation, deployment, operational monitoring, and an ingestion schedule. Partner enrollment and rewards remain planned in `ROADMAP.md`.
