# Signal Jobs

A global AI jobs marketplace in local alpha: employer posting and verification, reviewed source ingestion, candidate search, saved jobs and individual job pages. Companies can prepare paid-listing workflows locally; checkout currently simulates payment.

## Run locally

Python 3.10+ is required. No third-party Python packages are needed.

```bash
python3 backend/local_server.py
```

Open **http://127.0.0.1:8000**. SQLite data persists in `signal.sqlite3` and is ignored by Git. Use `--db /tmp/signal-test.sqlite3 --port 8010` for an isolated instance.

| Page | Purpose |
| --- | --- |
| `/` | Search jobs by keyword, country, work arrangement, employment type and salary currency; save jobs on this device. |
| `/jobs/{id}` | Full description, source, freshness and direct application link. |
| `/employer` | Company verification, job drafts, editing, preview, simulated checkout and posting status. |
| `/admin` | Company verification and paid-job moderation. |
| `/sources` | Source health, permission information and imported-job review. |

See [local development](docs/LOCAL_DEVELOPMENT.md) for the complete employer walkthrough. Browsing uses the shared database, with real empty/error states instead of illustrative openings. Drafts and unapproved, rejected or expired listings stay out of public search.

## Collect listings

Supported providers: Greenhouse, Lever (US/EU), Ashby, JobTech/Arbetsförmedlingen, USAJOBS, SmartRecruiters, Recruitee, Himalayas and Remotive. ATS providers can cover employers worldwide; actual coverage depends on configured and permitted boards. USAJOBS and some Recruitee sites require credentials.

```bash
cp sources.example.json sources.local.json
# Configure board identifiers, permission basis and explicitly enabled sources.
python3 backend/ingestion.py --config sources.local.json
# Optional continuous local refresh, once an hour:
python3 backend/ingestion.py --config sources.local.json --interval 3600
```

Examples are disabled. New listings enter review by default; approve them in `/sources`. Stable provider IDs and canonical application URLs prevent exact duplicates; refreshes preserve takedowns and return changed content to review. See [ingestion setup and provider documentation](docs/INGESTION.md). The [employer source catalogue](docs/SOURCE_CATALOGUE.md) contains 9,935 real board candidates with provenance; reachability and permission are tracked separately from enabled collection.

The standalone export tool also remains available:

```bash
python3 scraper.py --boards boards.json --sources sources.json --out jobs.json
python3 backend/import_jobs.py jobs.json --permission-basis "Reviewed source terms / license" --source-id local-import
```

Use the registry collector for reviewed refresh behavior, source health and scheduling. Do not commit credentials or local source configurations. Public access to an API is not blanket redistribution permission.

## Test

Node.js 22+ is recommended for the existing Worker tests and Playwright:

```bash
npm install
npm test
npx playwright install chromium
npm run test:browser
```

Browser tests use a disposable database and server, covering company verification → draft editing → simulated payment → approval → public search, candidate filters/details/saving, source review, and mobile/empty/error states. If needed, set `SIGNAL_BROWSER_EXECUTABLE` to an existing Chromium executable.

## Deployment boundary

The planned public address is **`https://signal.tnhc.dev`**, hosted on the owner's machine. A separate Python/Gunicorn browsing runtime now serves the candidate experience without exposing local identity or write routes. See [own-machine hosting](docs/OWN_MACHINE_HOSTING.md) for installation, database setup and the systemd service, and the [public deployment plan](docs/PUBLIC_DEPLOYMENT.md) for the remaining account/payment work.

This is a functioning **local alpha**, not a launched paid service. Local identity and moderator controls deliberately simulate accounts; do not expose this Python server publicly. Real sign-in, payment prices/secrets, tax/refund policy and production operations remain launch work.

`backend/worker.mjs` remains a separately tested legacy Cloudflare foundation; it is not the chosen hosting path. See [backend setup](backend/README.md), [product vision](docs/PRODUCT_VISION.md), [architecture](docs/MARKETPLACE_ARCHITECTURE.md) and [roadmap](docs/ROADMAP.md). The partner program is planned, including referrals, ATS/data and distribution partners; no commissions or terms are active.

The client styling and shared layout are adapted from the generated screens preserved under `docs/designs/`. Runtime content comes from the API, not their illustrative design data.
