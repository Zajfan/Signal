# Signal roadmap

Versioning follows the user's three-part scheme: `0.0.x` alpha, `0.x.0` beta, `1.0.0` first major release. Current: **0.0.4 alpha — local marketplace workflows; production deployment pending**.

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

## 0.0.4 — Local marketplace workflows (complete)

- Employer company profile, verification, owned draft editor/preview and posting dashboard.
- Simulated checkout and operations review before publication, with real SQLite/HTTP and browser tests.
- Configurable ingestion across seven providers, source health, exact deduplication, change review and stale expiry.
- Candidate search with global filters, pagination, saved IDs, job details and source/freshness disclosures.
- Local hourly JobTech ingestion into the private review queue; other boards require configuration and permission review.
- Explicit empty/loading/error states and desktop/mobile browser validation.

## Next — Production paid listing alpha

- Prepare public hosting at **`https://signal.tnhc.dev`**: production API parity, trusted accounts, persistent storage, scheduled ingestion, HTTPS and custom-domain routing. See [public deployment](PUBLIC_DEPLOYMENT.md).
- Allow anonymous candidate browsing while restricting employer actions to company members and operations to staff.
- Confirm products/prices/currency/durations and refund/tax policy.
- Configure hosted checkout, payment webhook and order reconciliation.
- Add posting approval, publish/pause/renew/close lifecycle and clearly labeled sponsored slots.
- Add employer performance: impressions, detail views and outbound apply clicks.

## 0.0.5 — Production ingestion and wider coverage

- Deploy the local ingestion capabilities to managed production infrastructure; add provider closure/deadline reconciliation and monitored retries.
- Configure USAJOBS credentials and run its adapter after access is authorized.
- Register public ATS boards with known company IDs and documented reuse rules.
- Expand source dashboard pagination, freshness/SLA metrics, cross-source provenance and fuzzy duplicate review.

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

## Planned — Partner program (release to be decided)

- Define partner categories: employer referrals, recruiting/agency partners, ATS and licensed data partners, and community/distribution partners.
- Add partner applications, onboarding, review, agreements and an account workspace.
- Track referred employers and attributable purchases, with transparent reporting and agreed attribution windows.
- Define referral rewards or revenue sharing, eligibility, payout thresholds, currencies, tax handling and fraud controls before enabling payouts.
- Provide approved referral links, campaign assets and, where appropriate, integration/API access.
- Record data licensing, redistribution rights, attribution and freshness responsibilities for source partners.
- Launch a small reviewed pilot before opening wider enrollment.

This is planned work only. Partner enrollment, commissions, payouts and terms are not active offers. The current implementation priorities remain employer portal, global ingestion, then candidate experience.

## Explicit launch decisions

1. Payment processor and merchant account.
2. Price per listing, promotion price/duration, bundle/subscription options and launch currencies.
3. Company verification approach and which countries can publish at launch.
4. AI job scope: both AI-native/AI-tool-using software jobs and roles building AI systems (the roadmap assumes both).
5. Data retention and whether Signal will ever collect applications/CVs (the roadmap assumes outbound application links first).
