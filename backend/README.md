# Signal marketplace backend foundation

This is the first server-side slice for persistent job data, employer drafts, paid checkout, and scheduled source refresh. It is deliberately separate from the current static Site build until the Site is converted to its Worker/D1 deployment profile.

## Included

- `migrations/0001_marketplace.sql` creates employers, employer listings, payment sessions, Stripe webhook deduplication, source status, imported listings, and moderation history.
- `worker.mjs` defines versioned routes for public listings and employer drafts, a Stripe Checkout adapter, a signed webhook handler, and a scheduled ingestion entry point for public JobTech and ATS feeds.
- Paid postings move from draft to awaiting payment to pending review. A successful payment alone never makes an employer listing public; moderation must approve it.

## Routes

| Route | Access | Purpose |
|---|---|---|
| `GET /api/v1/jobs` | Public | Search published jobs using `q`, `country`, `work_mode`, `limit`, and `offset`. |
| `GET /api/v1/employer/jobs` | Signed in | List the current employer's listings. |
| `POST /api/v1/employer/jobs` | Signed in | Create a validated draft; it is not searchable. |
| `POST /api/v1/employer/jobs/:id/checkout` | Listing owner | Create a Stripe Checkout session for a configured package. |
| `POST /api/v1/payments/stripe/webhook` | Stripe signature | Record payment idempotently and move a paid draft to moderation. |
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

The checkout route is intentionally unavailable until Stripe credentials and fixed price IDs are configured. No amount comes from the browser. The migration records the provider and package, while Stripe remains the system of record for the charged amount. Refund and tax handling still need to be selected before launch. Set `MODERATOR_USER_IDS` to a comma-separated list of trusted Site user IDs before using the moderator route.

The `scheduled` handler accepts a reviewed `INGEST_SOURCES` JSON array. An enabled source must include `source_id`, `ats`, and a recorded `permission_basis`; each feed is fetched serially, normalized, de-duplicated by source identity, refreshed, and stale records expire after 35 days. Configure a managed recurring Site task only after the Worker and D1 writer are deployed and verified.

## Deployment status

The hosted Site is currently static and owner-private. This backend is not live yet: deployment requires converting the Site to a Worker with a D1 binding, applying the migration, confirming the supported sign-in and public audience, configuring Stripe prices/secrets, and connecting the reviewed ingestion schedule. Keep paid post submission disabled until those checks are complete.
