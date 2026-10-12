# Global source discovery and live coverage expansion

**Goal:** Increase real AI job inventory beyond one 25-result Swedish feed and build a repeatable path to hundreds/thousands of employer sources.

**Scope:** Expand explicit redistribution feeds now; import a licensed ATS directory as discovery candidates, validate bounded samples of real board endpoints, and preserve separate states for discovered, reachable, permitted/enabled and published. A directory license covers the directory, not every employer's job text. Do not invent board slugs, evade blocks, email employers, purchase APIs or silently enable unreviewed redistribution.

**Architecture:** Existing Python/SQLite source registry, fixed-host provider adapters, per-source refresh intervals, bounded retries and per-host pacing. Candidate catalogue is separate from enabled collection. Source/apply links and provider attribution stay visible. New aggregate feeds use their own attribution link as application handoff and are excluded from onward syndication. Reviews and takedowns remain authoritative.

## Work

- [x] Add tested Himalayas and Remotive public-feed adapters, pagination, original-link attribution, expiry metadata and AI filtering. Provider references and previously collected live records are retained.
- [x] Add tested directory importer / supplied board-URL parser and bounded endpoint verification; persist provenance/license attribution and observed counts. Ship a substantial real candidate catalogue and an honest validation report.
- [x] Add source-level refresh intervals and bounded transient retry/pacing so a larger registry can run without hitting every provider hourly. Preserve source isolation and deterministic deduplication.
- [x] Expand source configuration and collect/publish classified jobs through explicitly enabled automatic publication. Local inventory and source accounting are recorded in `docs/SOURCE_CATALOGUE.md`; this does not claim manual review of every job.
- [x] Complete continuation fixes and coverage documentation; verify 120 backend/Worker tests and both browser suites; resolve independent code-review findings. Delivery follows the project's direct commit/push workflow on `main`.

## Continuation checkpoint

The prior commit implemented collection and added Jobicy, Remote OK and Arbeitnow, but left the source catalogue document absent and two discovery tests failing. The continuation fixes malformed-feed handling, stable IDs, attribution, employment/salary metadata, pagination, discovery title checks and multicast rejection. Database regression coverage checks that legacy Jobicy/Remote OK identities can be matched within their owning source and migrated, preserving takedowns even if a provider URL changes on the first upgraded refresh or a later one. Arbeitnow retains URL-based identity, so a changed provider URL cannot be linked automatically. No local inventory refresh or new publication is part of this verification pass.

Remaining expansion work: career-page HTML link extraction (only supplied URL parsing is implemented), renewed endpoint observations under the stricter validator, and broader manual relevance review. Historical observations overlap and two report filenames misidentify their provider; the catalogue documents actual contents rather than treating those reports as independent batches.

## Validation

Offline fixtures cover pagination stops, malformed feeds, attribution URLs, expired records, query-independent IDs, schedule skipping and retry bounds. Database tests cover deduplication, persisted removals and freshness. Real fetching uses bounded requests to documented public endpoints and retains errors in the coverage report. No assertion that a candidate directory equals active ingestion.
