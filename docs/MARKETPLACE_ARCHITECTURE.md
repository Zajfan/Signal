# Signal marketplace architecture

**Version:** 0.0.4 (local alpha)

## Product surfaces

| Surface | Main jobs |
|---|---|
| Public candidate marketplace | Search, filters, source/freshness, job detail, apply link, employer profile, SEO and saved-search entry points. |
| Employer workspace | Company verification, job editor, preview, checkout, listing status, renewals and performance. |
| Operations console | Company review, job moderation, source permissions/health, expiry, disputes, takedowns and audit history. |
| Ingestion service | Scheduled API/feed pulls, ATS source registry, normalization, classification, deduplication and expiry. |

## Core records

- `User`: identity, locale, account status.
- `Company`: verified legal/display identity, domains, country, billing profile, verification state.
- `CompanyMember`: user, company, role (`owner`, `recruiter`, `billing`, `viewer`).
- `Job`: normalized public job fields, status, `origin_type`, source provenance, publication/expiry timestamps, salary currency/period, language and moderation state.
- `JobSource`: provider, permission basis, source key, refresh policy, attribution and retention constraints.
- `Order` / `Payment`: selected package and immutable amount/currency/tax snapshot, provider IDs, idempotency key, paid/refunded state.
- `Placement`: organic/featured/sponsored window; visible `sponsored` disclosure and ranking budget.
- `Event`: privacy-limited impression, job-detail view, apply handoff and employer conversion events.
- `ModerationCase` / `AuditEvent`: staff decisions and evidence with actor and timestamps.

Source data should be separated from employer-controlled posts. A normalized job can point to one or more provenance records without pretending imported postings were submitted by Signal's customer.

## Job lifecycle

`draft → checkout_pending → payment_confirmed → moderation_pending → published → paused / expired / removed`

Imported jobs follow a distinct path: `fetched → normalized → policy_checked → published / review_required → rechecked → expired / removed`. A feed record is never silently upgraded into a paid employer listing.

## Paid posting flow

1. Employer creates an account and company; email/domain and business identity are verified.
2. Employer submits required job fields, salary range or an explicit “not disclosed,” application URL, country/work arrangement and expiry date.
3. Server validates the post and creates a server-side checkout session for a versioned product/price. The browser never chooses the authoritative amount.
4. The payment provider webhook is signature-verified and idempotently records payment. A successful redirect alone never marks an order paid.
5. The post enters human/automated moderation. Payment does not bypass policy.
6. Once approved, publish a canonical job detail URL and show the chosen promotion clearly.
7. Expire at the chosen end time; support employer pause/close, renewal, refund policy and audit trail.

Do not enable production checkout until a payment provider, merchant account, currencies, prices, VAT/invoicing, refund policy and applicable business terms are configured. Keep all keys in server-side secret storage.

## Search and classification

- Use a global core schema with ISO country codes, normalized locations, time zones, BCP-47 language, salary amount/currency/period and source timestamps.
- Separate `job_family` (AI/ML engineering, AI-assisted software engineering, research, data, infrastructure, product/design, sales/operations) from `ai_work_signals` (tools, model work, agent systems, evaluations, AI-enabled SDLC).
- Support literal keyword search first, then a later hybrid semantic ranker. Never present a heuristic score as certainty; expose reason chips such as “mentions Claude Code” or “builds evaluation systems.”
- Rank organic relevance and recency separately from paid placement. Clearly label the latter and cap its impact.
- Search results are not job detail pages. Add valid JobPosting structured data only to one-job detail pages after the full listing, expiry and apply-path policies are implemented.

## System shape

The intended public origin is **`https://signal.tnhc.dev`**. Candidate search and job pages will be accessible without an account; employer and staff actions require server-enforced authentication and roles. See [the deployment sequence](PUBLIC_DEPLOYMENT.md). Localhost remains the development environment.

The current `index.html` and `web/` client use the Python/SQLite API for employer, operations and candidate workflows. `backend/public_server.py` provides a separate browsing-only WSGI runtime with read-only database access and a public shell. Ingestion runs as a separate serialized CLI process. The Cloudflare Worker is retained as a legacy alternative, not the chosen host. For the complete public marketplace, add:

- responsive web client with public, crawlable job-detail routes;
- authenticated API for employers, candidates and operations;
- relational database for tenant isolation, jobs, orders, source registry and audit;
- queue/worker for scheduled ingestion, payment webhooks, email and expiry;
- search index with per-country/language analyzers once volume warrants it;
- object storage only for authorized company assets; avoid candidate resumes initially;
- observability for connector freshness, duplicate rates, payments and publishing.

The selected hosting location is the owner's own machine. The first public browsing runtime uses Gunicorn and SQLite behind the existing HTTPS proxy or tunnel; see [own-machine hosting](OWN_MACHINE_HOSTING.md). Authentication, company isolation and production billing remain separate implementation stages. Revisit database/search infrastructure as load and availability requirements grow.

## Security and operations

- Enforce company-scoped authorization on the server for every write and analytics request.
- Verify payment webhook signatures, deduplicate event IDs, and reconcile provider settlement/refunds.
- Rate limit login, posting, application handoffs, import and report actions.
- Sanitize employer rich text, validate outbound URLs, restrict upload types/size and guard against SSRF in source connectors.
- Separate staff permissions from employer roles; log privileged actions.
- Keep PII collection minimal; define retention and deletion paths before adding CV uploads or candidate profiles.
- Include incident, backup/restore, abuse and takedown procedures before public launch.
