# Portable public browsing runtime

**Goal:** Package Signal's existing candidate experience for hosting at `signal.tnhc.dev` without depending on Cloudflare Workers or exposing local account simulation.

**Scope:** Public browsing release foundation. The full employer/paid marketplace remains the product goal; this runtime deliberately has no write or account routes until production authentication is implemented. Cloudflare domain registration does not determine the application host. Exact proxy/tunnel configuration awaits the existing hosting details.

**Architecture:** A separate WSGI application behind Gunicorn reuses Python search, details and facets with read-only SQLite connections. The existing local development server and ingestion process continue to operate separately. Public static assets are explicitly allowed; the public shell reuses the established design without local workspace controls. No DNS, deployment or production data mutations in this step.

## Tasks

- [x] Add real SQLite/WSGI tests for search, details, filters, visibility, static routing, unavailable databases and rejected development identities/write routes. Confirm failures before implementation.
- [x] Add the public runtime, read-only search connections, public shell and minimal client capability handling. Retain local behavior.
- [x] Package the runtime with a pinned server dependency and a user systemd service; document native startup and future proxy attachment.
- [x] Run backend checks, native Gunicorn and public browser smoke tests with disposable data; review changes. Delivery uses main directly as requested.

## Contracts

- `GET /api/v1/jobs`: existing `{jobs,total,limit,offset}` and all local filters.
- `GET /api/v1/jobs/facets`: existing countries, currencies and employment types.
- `GET /api/v1/jobs/{id}`: existing public fields, hidden/expired/unknown returns 404.
- `/api/v1/health`: public runtime and capabilities, with database readiness; unavailable database returns 503 without filesystem details.
- `/`, `/jobs/{id}`: public shell; removed jobs return HTTP 404 while allowing the client to show its existing unavailable message.
- Development/employer/admin/payment APIs and private pages are unavailable; supplied identity headers do not alter this.
- GET and HEAD only; API errors use JSON, assets use correct MIME types, unknown assets return 404.
- Public DB access uses SQLite `mode=ro`; never initialize an empty database on a web request.
- Testing uses temporary fixture databases only; no local data copying or publication.

## Verification results

61 backend checks pass. Both local-marketplace and public Gunicorn browser suites pass, including 200 saved jobs, pagination, long Unicode queries, unavailable/empty states and mobile layout. Review findings are resolved. The public preview runs on loopback port 8001; no DNS or internet exposure was configured.
