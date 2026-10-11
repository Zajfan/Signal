# Local source collection

The collector supports Greenhouse, Lever (US and EU), Ashby, JobTech, USAJOBS, SmartRecruiters and Recruitee. These are configurable provider connectors, not a claim that Signal has indexed every employer using them. JobTech is a Swedish public service; USAJOBS requires credentials; the ATS connectors cover companies operating in many countries.

## Configure and run

Copy `sources.example.json` to `sources.local.json`. Example entries are disabled. Replace board slugs, review reuse permission, record `permission_basis` and `terms_url`, then explicitly enable approved sources. An accessible API is not by itself permission to redistribute a company's advertisements.

```bash
python3 backend/ingestion.py --config sources.local.json
python3 backend/ingestion.py --config sources.local.json --interval 3600
```

The first command collects once. The second runs one fetch cycle at a time, then waits one hour. It reads configuration each cycle and stops on Ctrl+C/SIGTERM. It uses `signal.sqlite3`; override with `--db`. A source failure is recorded while other sources continue. One-shot runs return nonzero if a source failed.

Open `/sources` to see source health and review imports. New records are private until reviewed. Approve makes them public; reject records a takedown that later refreshes cannot silently reverse. `auto_publish: true` explicitly allows automatic publication for a reviewed source; leave it false unless that is intended. Changes to approved content return to review by default.

Deduplication uses provider record IDs and canonical application URLs, dropping known tracking parameters while preserving job identifiers. This handles exact duplicates and overlapping searches; it is not fuzzy matching across rewritten advertisements. A duplicate from another source does not transfer ownership. Source fetches are atomic per batch: malformed records fail the source batch instead of marking a partial import successful. Entries older than 35 days expire; a failed or bounded fetch does not immediately withdraw absent records. Provider closures/deadlines are not yet continuously reconciled, so the original employer page remains the source of current availability.

The local-only `ingest_job_metadata`, `ingest_run_metadata` and `import_review_events` tables are created idempotently. Source health records the last attempt, successful fetch and error. The current operations queue displays up to 500 pending imports per load; review a batch and refresh to reach the next one.

## Provider details

- [SmartRecruiters Posting API](https://developers.smartrecruiters.com/docs/endpoints): paginated public company postings plus detail requests. Configure `limit` and `max_pages` to bound requests. Details are fetched from the fixed official host.
- [Recruitee Careers Site API](https://docs.recruitee.com/reference/offers): company subdomain and `offers` response. Set `token_env` to the name of an environment variable for `X-Careers-Sites-Token`. [Recruitee authentication guidance](https://docs.recruitee.com/reference/authentication-1) announces a token requirement from February 10, 2027; use an employer-provided token where required. Never commit tokens.
- [JobTech JobSearch](https://data.arbetsformedlingen.se/dataservice/jobsearch/): publicly accessible CC0 data, without API registration. Preserve the original posting link. Query overlap deduplicates by provider job ID.
- Lever: set `region: "eu"` for `api.eu.lever.co`; otherwise use the US endpoint.
- USAJOBS: set `USAJOBS_API_KEY` and `USAJOBS_USER_AGENT`. The current collector bounds this search to the configured page size.

Country/currency fields are retained when providers supply them. Missing metadata remains unknown instead of inventing a location or converting currency. Salary periods are not universally normalized; candidates should confirm the period on the original posting. Generic code-review language alone no longer qualifies a role as AI-related.

## Existing file imports

The original `backend/import_jobs.py` remains available for manual exports, but use the registry collector for source health, canonical deduplication, and reviewed refresh behavior. Its `--publish` option is an explicit manual publication action; it does not add source scheduling.
