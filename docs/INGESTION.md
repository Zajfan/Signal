# Local source collection

The collector supports Greenhouse, Lever (US and EU), Ashby, JobTech, USAJOBS, SmartRecruiters, Recruitee, Himalayas and Remotive. These are configurable provider connectors, not a claim that Signal has indexed every employer using them. JobTech is a Swedish public service; USAJOBS requires credentials; the ATS connectors cover companies operating in many countries.

## Configure and run

Copy `sources.example.json` to `sources.local.json`. Example entries are disabled. Replace board slugs, review reuse permission, record `permission_basis` and `terms_url`, then explicitly enable approved sources. An accessible API is not by itself permission to redistribute a company's advertisements.

```bash
python3 backend/ingestion.py --config sources.local.json
python3 backend/ingestion.py --config sources.local.json --interval 3600
```

The first command collects once. The second runs one fetch cycle at a time, then waits one hour. Each source also has a persisted `refresh_interval_seconds` (0–604800); sources that are not due are deferred, including after failed requests. Himalayas defaults to daily. Remotive has a shared six-hour minimum across all configured searches, with the least recently attempted query taking the next slot. Use one unfiltered Remotive source to cover its feed without splitting the budget. It reads configuration each cycle and stops on Ctrl+C/SIGTERM. It uses `signal.sqlite3`; override with `--db`. A source failure is recorded while other sources continue. One-shot runs return nonzero if a source failed.

Open `/sources` to see source health and review imports. New records are private until reviewed. Approve makes them public; reject records a takedown that later refreshes cannot silently reverse. `auto_publish: true` explicitly allows automatic publication for a reviewed source; leave it false unless that is intended. Changes to approved content return to review by default.

Deduplication uses provider record IDs and canonical application URLs, dropping known tracking parameters while preserving job identifiers. This handles exact duplicates and overlapping searches; it is not fuzzy matching across rewritten advertisements. A duplicate from another source does not transfer ownership. Source fetches are atomic per batch: malformed records fail the source batch instead of marking a partial import successful. Entries older than 35 days expire; a failed or bounded fetch does not immediately withdraw absent records. Provider expiry timestamps, when supplied by a connector, hide listings immediately in search and prevent review approval after expiry. Other closures are not yet continuously reconciled; the original posting remains the source of current availability.

The additive `0002_import_details.sql` migration stores imported expiry, salary period and onward-syndication permission, plus provider request budgets. Local startup/ingestion applies migrations idempotently. Public browsing remains read-only: migrate its database before restarting the public process (see [hosting](OWN_MACHINE_HOSTING.md)).

The local-only `ingest_job_metadata`, `ingest_run_metadata` and `import_review_events` tables are created idempotently. Source health records the last attempt, successful fetch and error. The current operations queue displays up to 500 pending imports per load; review a batch and refresh to reach the next one.

## Global feeds and employer discovery

`data/source-candidates.json` contains real employer board identifiers with directory attribution and provenance. Candidates remain disabled. Use `backend/discovery.py` to import directory updates, extract supported board URLs from supplied career-page HTML, and validate bounded batches. See [the source catalogue](SOURCE_CATALOGUE.md) for commands, licensing and validation results. A reachable board or directory license does not approve republication of its job descriptions.

The global feed examples have explicit API backfill/sharing terms. After reviewing those terms, enable them in your local configuration. Keep `auto_publish` false for manual review, or explicitly set it true to publish AI-classified records from a reviewed source. Classification detects terms in job text; it does not guarantee every role focuses primarily on AI. No arbitrary website crawler or paywall bypass is included.

## Provider details

- [Himalayas API](https://himalayas.app/api): job-board backfill allowed with visible Himalayas attribution and links to its listings. No onward syndication to other job boards. With `query`, uses search pages (20 records/page); without it, follows browse cursors. `max_pages` is bounded at 100. Poll daily. This indexes a bounded window, not every job on Himalayas.
- [Remotive API](https://github.com/remotive-com/remote-jobs-api): visible attribution and original Remotive URLs required; no signup gate or onward syndication. Fetch the complete available feed once per six hours at most; the provider already delays its public API by 24 hours. No immediate HTTP retry for this provider. Feed size varies and is not the size of Remotive's full website.
- HTTP requests use per-host pacing and bounded retries for transient failures; excessive `Retry-After` values end the attempt instead of being ignored. Sources retain errors for operations review.

- [SmartRecruiters Posting API](https://developers.smartrecruiters.com/docs/endpoints): paginated public company postings plus detail requests. Configure `limit` and `max_pages` to bound requests. Details are fetched from the fixed official host.
- [Recruitee Careers Site API](https://docs.recruitee.com/reference/offers): company subdomain and `offers` response. Set `token_env` to the name of an environment variable for `X-Careers-Sites-Token`. [Recruitee authentication guidance](https://docs.recruitee.com/reference/authentication-1) announces a token requirement from February 10, 2027; use an employer-provided token where required. Never commit tokens.
- [JobTech JobSearch](https://data.arbetsformedlingen.se/dataservice/jobsearch/): publicly accessible CC0 data, without API registration. Preserve the original posting link. Query overlap deduplicates by provider job ID.
- Lever: set `region: "eu"` for `api.eu.lever.co`; otherwise use the US endpoint.
- USAJOBS: set `USAJOBS_API_KEY` and `USAJOBS_USER_AGENT`. The current collector bounds this search to the configured page size.

Country/currency fields are retained when providers supply them. Missing metadata remains unknown instead of inventing a location or converting currency. Explicit salary periods from supported feeds are retained and displayed; unknown periods stay unlabeled, and no annualization/currency conversion is performed. Country codes are assigned only for a recognized single-country restriction; multi-country and timezone restrictions remain in the location text. The country filter currently matches the stored single-country code, not all remote eligibility regions. Generic code-review language alone no longer qualifies a role as AI-related.

## Existing file imports

The original `backend/import_jobs.py` remains available for manual exports, but use the registry collector for source health, canonical deduplication, and reviewed refresh behavior. Its `--publish` option is an explicit manual publication action; it does not add source scheduling.
