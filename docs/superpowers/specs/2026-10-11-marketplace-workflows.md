# Signal marketplace workflows

Approved scope: implement employer portal, global ingestion, and candidate experience in that order. This release makes the local SQLite-backed marketplace usable end to end. Production identity, merchant setup and deployment remain separate launch gates.

## 1. Employer portal

Provide `/employer` with company profile and verification state, a job dashboard, editable drafts, public preview, and explicit simulated checkout. Provide `/admin` with company and paid-job review queues. Use the existing ownership and publication model: only the owner reads/edits a draft, only drafts are editable, verified company required for checkout, paid jobs require moderator approval. Local identity controls live in a clearly labeled development panel. Validation covers required fields, AI relevance, countries, URL schemes and salary amounts/currency. Persist through SQLite; do not use browser storage as the source of job truth. Keep the current Worker API usable and document local-only additions.

## 2. Global ingestion

Extend the existing collector with documented public ATS connectors, preserving source identifiers, country codes, currencies, application URLs and explicit AI signals. Use a reviewed source registry with disabled examples; registration never implies redistribution permission. Run scheduled collection through an explicit CLI process using the local database, with per-source success/failure state, deduplication on provider/job identity and canonical application URLs, stale expiry, failure isolation, and moderation before publication by default. Provide operations controls for reviewing imported listings and viewing source health. Do not expire unseen jobs immediately after a partial or failed fetch.

## 3. Candidate experience

Use the database-backed search API with pagination, query, country, work arrangement, employment type and salary currency filters. Detail pages have stable IDs, complete descriptions, salary currency, source, freshness and direct application links. Saved IDs stay local to the browser. Distinguish empty data, no matches, loading and network errors. No illustrative jobs or heuristic match probabilities in live database results. Expired, unpublished and rejected jobs never appear in public search or public details.

## Architecture

Python standard library HTTP server and SQLite remain the local runtime. Extract persistence and validation into focused modules as the routes grow. Plain HTML/CSS/JS with shared assets and 12ui-derived design, no frontend framework migration. A small versioned migration runner handles subsequent schema changes. Ingestion imports reusable collector functions. Worker remains a separate production foundation, with any route differences explicitly documented.

## Validation

Use real SQLite databases for lifecycle, ownership, expiry, search, ingestion idempotency and failure isolation tests. Mock network transport only for connector fixtures. Use browser checks at desktop/mobile sizes for create/edit/preview, company verification, simulated payment, review and publication, search/detail/save, source review and empty/error states. Test data must use a disposable database. Verify the development server against the user's existing database after restarting it.
