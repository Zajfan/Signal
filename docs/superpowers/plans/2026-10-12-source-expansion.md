# Global source discovery and live coverage expansion

**Goal:** Increase real AI job inventory beyond one 25-result Swedish feed and build a repeatable path to hundreds/thousands of employer sources.

**Scope:** Expand explicit redistribution feeds now; import a licensed ATS directory as discovery candidates, validate bounded samples of real board endpoints, and preserve separate states for discovered, reachable, permitted/enabled and published. A directory license covers the directory, not every employer's job text. Do not invent board slugs, evade blocks, email employers, purchase APIs or silently enable unreviewed redistribution.

**Architecture:** Existing Python/SQLite source registry, fixed-host provider adapters, per-source refresh intervals, bounded retries and per-host pacing. Candidate catalogue is separate from enabled collection. Source/apply links and provider attribution stay visible. New aggregate feeds use their own attribution link as application handoff and are excluded from onward syndication. Reviews and takedowns remain authoritative.

## Work

- [ ] Add tested Himalayas and Remotive public-feed adapters, pagination, original-link attribution, expiry metadata and AI filtering. Verify current provider documentation and sample live responses.
- [ ] Add tested directory importer / board-URL discovery and bounded endpoint verification; persist provenance/license attribution and observed counts. Ship a substantial real candidate catalogue and an honest validation report.
- [ ] Add source-level refresh intervals and bounded transient retry/pacing so a larger registry can run without hitting every provider hourly. Preserve source isolation and deterministic deduplication.
- [ ] Expand approved source configuration, collect real data, review relevance/metadata and publish eligible listings under the user's request for more listed jobs. Preserve rejected records and source requirements.
- [ ] Update coverage documentation, run backend/browser checks, obtain review, commit and push directly to main. Report actual before/after jobs, active sources, reachable boards and candidate counts.

## Validation

Offline fixtures cover pagination stops, malformed feeds, attribution URLs, expired records, query-independent IDs, schedule skipping and retry bounds. Database tests cover deduplication, persisted removals and freshness. Real fetching uses bounded requests to documented public endpoints and retains errors in the coverage report. No assertion that a candidate directory equals active ingestion.
