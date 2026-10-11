# Signal Marketplace Workflows Implementation Plan

> Execute the approved milestones in order, inline, with tests and review after each milestone.

**Goal:** Make the local marketplace usable for employers, source operators and candidates.
**Architecture:** Keep SQLite and the Python local server; introduce shared validation/persistence, reusable UI assets and a scheduled ingestion CLI. Preserve the existing Worker foundation and document production gaps.
**Tech stack:** Python standard library, SQLite, HTML/CSS/JavaScript, Node's built-in tests; Playwright for browser verification.
**Spec:** `docs/superpowers/specs/2026-10-11-marketplace-workflows.md`.

## Global constraints

- Implement employer portal, ingestion, then candidate experience.
- Bind local runtime to loopback; never treat development identity headers as production authentication.
- No real charge, no invented prices, no publication without review.
- Database-backed listings; no production demo records.
- Preserve existing data across restart and migrations.

## Milestone 1 — Employer posting

- [x] Add SQLite regression tests for owned draft reads/edits, validation, verification, payment and review gates.
- [x] Implement employer persistence and API routes including local operations queues.
- [x] Generate and integrate employer dashboard, company form, job editor/preview and review screens.
- [x] Verify a complete employer lifecycle in a disposable browser/database session.

Files: `backend/local_server.py`, `backend/marketplace.py`, `backend/local_server.test.py`, `web/`, `index.html`.
Contract: employer job responses use snake_case database fields, errors use `{error}`, list responses use `{jobs}`. PATCH `/api/v1/employer/jobs/:id` accepts complete draft fields and permits only the owner in draft state. Admin queue GET routes require local admin identity.

## Milestone 2 — Scheduled source ingestion

- [x] Read official provider API docs and add fixture tests before adding connectors.
- [x] Add additional public ATS connectors and preserve global metadata.
- [x] Add registry-backed ingestion, idempotent upserts, review defaults, recorded failures and expiry.
- [x] Add CLI scheduler and source/review operations UI; verify failure isolation and repeat imports.

Files: `scraper.py`, `backend/ingestion.py`, `backend/ingestion.test.py`, `sources.example.json`, `web/`.
Contract: source registry stores permission basis and explicit enable/publish choices; new imports use needs_review unless auto-publication was explicitly configured. Scheduler uses `python3 backend/ingestion.py --config sources.example.json --interval 3600`.

## Milestone 3 — Candidate search and details

- [x] Add real SQLite tests for pagination, country/work/type/currency filters and hidden/expired details.
- [x] Implement public detail and facet APIs and consistent public job response fields.
- [x] Integrate responsive database search, details, saved jobs, source/freshness and currency-aware salary display.
- [x] Exercise desktop/mobile browser flows, update README/roadmap, run all tests and inspect the final diff.

Files: `backend/marketplace.py`, `backend/local_server.py`, `backend/local_server.test.py`, `web/`, `index.html`, `README.md`, `docs/ROADMAP.md`.
Contract: GET `/api/v1/jobs` returns `{jobs,total,limit,offset}`; GET `/api/v1/jobs/:id` only returns a publicly visible job. Country is ISO alpha-2; salaries are compared only with an explicit currency filter.
