# Signal marketplace backend and local runtime

Run the SQLite-backed local app on a development machine with Python 3.9+; no third-party Python packages are required. The Cloudflare Worker remains available as the production runtime foundation.

## Run Signal locally

From the repository root:

```bash
python3 backend/local_server.py
```

Run its focused SQLite checks with `python3 backend/local_server.test.py`.

Open `http://127.0.0.1:8000`. The server creates `signal.sqlite3` from the shared migration. It binds only to loopback. Employer endpoints accept `X-Local-User-Id` and `X-Local-User-Email`; moderator routes accept `X-Local-Admin: true`. These headers are intentionally spoofable and are only for local testing. The local checkout flow is simulated and never contacts Stripe or charges money.

Use another database or port with `--db /tmp/signal-dev.sqlite3 --port 8010`.

### Import scraper results

```bash
python3 scraper.py --boards boards.json --sources sources.json --out jobs.json
python3 backend/import_jobs.py jobs.json --permission-basis "Reviewed source terms / license" --source-id local-ai-boards
```

Imports default to `needs_review` and stay out of public search. After confirming the source permits redistribution and checking the records, add `--publish` to publish them locally. The source provenance is stored in `ingest_sources`.

### Test employer posting locally

1. Read `/api/v1/employer/profile` and `/api/v1/employer/jobs` using local identity headers.
2. Submit company verification with `POST /api/v1/employer/company-verification`.
3. Approve the company locally with `POST /api/v1/admin/employers/{user_id}/verify` and `X-Local-Admin: true`.
4. Create a draft with `POST /api/v1/employer/jobs`, then request `/api/v1/employer/jobs/{id}/checkout`.
5. Complete the simulated payment at the returned `/api/v1/local/payments/{id}/complete` route.
6. Approve it with `POST /api/v1/admin/jobs/{id}/moderate` and `X-Local-Admin: true`.

Example local company review:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/employer/company-verification \
  -H 'Content-Type: application/json' -H 'X-Local-User-Id: employer-1' \
  -d '{"company_name":"Example Ltd","website_url":"https://example.com"}'
curl -X POST http://127.0.0.1:8000/api/v1/admin/employers/employer-1/verify \
  -H 'Content-Type: application/json' -H 'X-Local-Admin: true' -d '{"action":"approve"}'
```

Only published jobs appear in `GET /api/v1/jobs`. Employer listings are searchable alongside approved imported jobs.

## Included

- `migrations/0001_marketplace.sql` creates employers, employer listings, payment sessions, Stripe webhook deduplication, source status, imported listings, and moderation history.
- `worker.mjs` defines versioned routes for public listings and employer drafts, a Stripe Checkout adapter, a signed webhook handler, and a scheduled ingestion entry point for public JobTech and ATS feeds.
- Paid postings move from draft to awaiting payment to pending review. A successful payment alone never makes an employer listing public; moderation must approve it.

## Routes

| Route | Access | Purpose |
|---|---|---|
| `GET /api/v1/jobs` | Public | Search published jobs using `q`, `country`, `work_mode`, `limit`, and `offset`. |
| `GET /api/v1/employer/jobs` | Signed in | List the current employer's listings. |
| `GET /api/v1/employer/profile` | Signed in | Read the current company verification state. |
| `POST /api/v1/employer/jobs` | Signed in | Create a validated draft; it is not searchable. |
| `POST /api/v1/employer/company-verification` | Signed in | Submit company name and HTTPS website for manual verification. |
| `POST /api/v1/employer/jobs/:id/checkout` | Listing owner | Create a Stripe Checkout session for a configured package. |
| `POST /api/v1/payments/stripe/webhook` | Stripe signature | Record payment idempotently and move a paid draft to moderation. |
| `POST /api/v1/admin/employers/:user_id/verify` | Configured moderator | Approve or reject an employer company. |
| `POST /api/v1/admin/jobs/:id/moderate` | Configured moderator | Approve or reject a paid listing awaiting review. |
| `GET /api/v1/health` | Public | Liveness check. |

Employer routes expect the Site dispatch identity headers and must only be mounted behind the Site's trusted authentication boundary. Email is a contact/display attribute; the stable Site user ID owns the record. Do not deploy this Worker as an unprotected standalone endpoint.

## Runtime configuration

The Worker needs a D1 `DB` binding. Configure these values as hosted secrets or runtime variables; never put values in source:

- `STRIPE_SECRET_KEY` and `STRIPE_WEBHOOK_SECRET` as secrets.
- `STRIPE_PRICE_STANDARD` and `STRIPE_PRICE_FEATURED` as Stripe Price IDs after package prices are chosen.
- `USAJOBS_API_KEY` and `USAJOBS_USER_AGENT` as runtime values when the USAJOBS API key is granted.
- `INGEST_SOURCES` as a JSON array of reviewed, enabled feeds. Each entry needs `source_id`, `ats`, and `permission_basis`; ATS entries also need a public `board`. Do not enable a source until its terms/redistribution permission are reviewed.

Example for an approved JobTech query:

```json
[{"source_id":"se-jobtech-ai","ats":"jobtech","label":"Arbetsförmedlingen JobTech","country_code":"SE","query":"AI","limit":50,"max_pages":2,"enabled":true,"permission_basis":"CC0 public JobTech service","terms_url":"https://data.arbetsformedlingen.se/dataservice/data-service-jobsearch/"}]
```

An employer can save drafts before verification, but checkout and publication require a moderator-verified company. Checkout is intentionally unavailable until Stripe credentials and fixed price IDs are configured. No amount comes from the browser. The migration records the provider and package, while Stripe remains the system of record for the charged amount. Refund and tax handling still need to be selected before launch. Set `MODERATOR_USER_IDS` to a comma-separated list of trusted Site user IDs before using moderator routes.

The `scheduled` handler accepts a reviewed `INGEST_SOURCES` JSON array. An enabled source must include `source_id`, `ats`, and a recorded `permission_basis`; each feed is fetched serially, normalized, de-duplicated by source identity, refreshed, and stale records expire after 35 days. Configure a managed recurring Site task only after the Worker and D1 writer are deployed and verified.

## Deployment status

The hosted Site is currently static and owner-private. This backend is not live yet: deployment requires converting the Site to a Worker with a D1 binding, applying the migration, confirming the supported sign-in and public audience, configuring Stripe prices/secrets, and connecting the reviewed ingestion schedule. Keep paid post submission disabled until those checks are complete.
