# Public deployment: signal.tnhc.dev

**Planned canonical origin: `https://signal.tnhc.dev`.** Signal is intended to be a publicly accessible global marketplace. Localhost is the development environment, not the final hosting model. This document records the target; DNS, certificates and hosting have not been provisioned by this change.

**Hosting decision:** run the application on the owner's own machine. Cloudflare manages `tnhc.dev`; Workers/D1 are not required. A separate Python/Gunicorn public browsing runtime and systemd template are now available in [own-machine hosting](OWN_MACHINE_HOSTING.md). Its employer/staff/payment endpoints remain unavailable pending real authentication and billing integration.

## Public and private access

| Surface | Intended access |
| --- | --- |
| `/`, `/jobs/{id}` | Public browsing, search and application links without signing in. |
| `/employer` | Authenticated company members; all reads and writes scoped to their company. |
| `/admin`, `/sources` | Authorized Signal staff only, enforced by the API. |
| Payment webhook | Public endpoint with provider signature verification and event deduplication. |
| Ingestion worker | Managed background process; no public collection trigger. |

Keep the frontend and `/api/v1/` on the same origin. Use the configured public origin for checkout return URLs, account callbacks and future canonical/structured-data links. Keep local development URLs separate so local tests never target production.

## Implementation sequence

1. **Complete the own-machine runtime.** Public search, details and facets now reuse the existing Python implementation through a separate WSGI entry point. Add authenticated employer editing, moderation queues and ingestion review as later stages. The legacy Cloudflare Worker is retained in the repository but is not the selected deployment path.
2. **Replace simulated identity and payments.** Add verified sessions, company membership and staff roles. Neither `X-Local-*` headers nor user-supplied `oai-authenticated-*` headers are trusted authentication on a public server. The existing Worker assumes a trusted Site dispatcher; standalone hosting must replace that boundary or cryptographically verify identity. Remove local identity controls and simulated payment routes from the public build. Configure server-owned prices and signed payment webhooks when paid posting launches.
3. **Provision persistent services.** Create production storage, apply reviewed migrations, configure secrets outside Git and schedule ingestion with reviewed source permissions. Verify backups and restore, source freshness, moderation, expiry and payment reconciliation. Do not copy the local development database into production as seed data.
4. **Verify a staging deployment.** Test anonymous browsing, cross-company isolation, staff access, payment sandbox callbacks, imported-job review, expiry and direct navigation to job URLs. Confirm repository files, credentials and databases cannot be downloaded. Confirm local identity headers grant no privileges.
5. **Connect `signal.tnhc.dev`.** Attach the custom hostname using the selected host's prescribed DNS records, enable a valid TLS certificate and redirect HTTP to HTTPS. The exact DNS record and destination depend on that host; do not guess a server address. Configure this origin in authentication and payment return settings. Keep staging out of search indexes.
6. **Verify and operate the public site.** Run smoke tests through the actual HTTPS hostname, verify direct links and error pages, check monitoring and rollback, then open public access. Paid posting remains unavailable until its merchant, pricing and refund settings have been validated.

The Python local server remains loopback-only. Port forwarding or exposing it through a public tunnel is not the deployment path. A custom hostname alone does not provide the account isolation and payment processing the marketplace needs.

## Decisions still required before deployment

- Existing machine's HTTPS proxy/tunnel routing and DNS access for `tnhc.dev`.
- Authentication provider and account recovery flow.
- Merchant account, listing prices/currencies and billing/refund policies.
- Production source registry, permitted data reuse and operational ownership.

The partner program remains a planned feature in [the roadmap](ROADMAP.md); it is not required for the first public browsing release.
