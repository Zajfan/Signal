# Signal roadmap

Versioning follows the user's three-part scheme: `0.0.x` alpha, `0.x.0` beta, `1.0.0` first major release. Current: **0.0.3 alpha — backend foundation, not yet deployed**.

## 0.0.1 — AI jobs board prototype (complete)

- Search/filter interface, illustrative preview cards, local saved jobs.
- Greenhouse, Lever and Ashby command-line feeds and JSON import.
- Private static preview and public GitHub source.

## 0.0.2 — Marketplace foundation (complete)

- Product vision, source permission model, architecture and marketplace lifecycle.
- Add official public-service connectors and documented source registry.
- Define candidate and employer surfaces: discover, job detail, post a job, employer plans and company workspace.
- Mark prices and checkout as unconfigured until business decisions and a merchant account exist.

## 0.0.3 — Backend foundation (in progress)

- Add D1 schema for employers, job posts, payments, imported jobs, source health and moderation history.
- Implement API foundations for public listings, employer drafts, Checkout, signed webhooks and moderator review.
- Implement source normalization and scheduled ingestion entry point for JobTech and public ATS feeds.
- Convert the private static preview to a full-stack Worker/D1 Site and apply the schema migration.
- Confirm public visitor access and a supported company account/verification path.

## 0.0.4 — Paid listing alpha

- Confirm products/prices/currency/durations and refund/tax policy.
- Configure hosted checkout, payment webhook and order reconciliation.
- Add posting approval, publish/pause/renew/close lifecycle and clearly labeled sponsored slots.
- Add employer performance: impressions, detail views and outbound apply clicks.

## 0.0.5 — Reliable source ingestion

- Configure recurring ingestion, tested connectors, source status, dedupe and stale-job cleanup.
- Configure USAJOBS credentials and run its adapter after access is authorized.
- Register public ATS boards with known company IDs and documented reuse rules.
- Source dashboard, freshness/SLA metrics, takedowns and manual review.

## 0.1.0 — Beta marketplace

- Responsive public marketplace with localized routes and reliable per-job pages.
- Country/language/salary normalization, quality reporting, company profiles and job alerts.
- Search-engine job-detail structured data only after content and expiry checks pass.
- First distribution/ATS partnerships and employer feedback loop.

## 1.0.0 — Public launch gate

- Production data, payments, account recovery, moderation and support verified.
- Security/privacy review, source-rights matrix and legal/business terms reviewed for launch markets.
- Operational dashboards, backups, alerting, incident process and rollback tested.
- Public access enabled deliberately after the complete service is ready.

## Explicit launch decisions

1. Payment processor and merchant account.
2. Price per listing, promotion price/duration, bundle/subscription options and launch currencies.
3. Company verification approach and which countries can publish at launch.
4. AI job scope: both AI-native/AI-tool-using software jobs and roles building AI systems (the roadmap assumes both).
5. Data retention and whether Signal will ever collect applications/CVs (the roadmap assumes outbound application links first).
