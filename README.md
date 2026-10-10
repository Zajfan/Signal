# Signal Jobs

Signal Jobs is a focused job discovery board for software developers who build with AI. It combines a simple public ATS scraper with a searchable listings interface, saved jobs, filters, and JSON import.

## What's here

- `index.html` — responsive listings platform. Saved jobs and imported listings persist in this browser.
- `scraper.py` — dependency-free collector for public Greenhouse, Lever, and Ashby boards, Sweden's JobTech/Arbetsförmedlingen search API, and USAJOBS (API key required).
- `boards.json` — editable public ATS board configuration.
- `sources.json` — sample public employment-service queries.
- `docs/` — product vision, architecture, source policy, and staged roadmap for the global marketplace.
- `backend/` — D1 schema and a not-yet-deployed Worker API foundation for shared listings, employer posts, paid checkout, moderation, and scheduled ingestion.

The six listings shown before importing are illustrative preview records, not verified current openings. The scraper reads live public ATS feeds when you run it and writes the resulting records to `jobs.json`.

## Run a scrape

Python 3.10+ is recommended. No pip packages are required.

```bash
python3 scraper.py --boards boards.json --sources sources.json --out jobs.json
```

By default, the scraper keeps jobs whose descriptions contain AI development signals. Include all jobs from configured boards with:

```bash
python3 scraper.py --boards boards.json --sources sources.json --out jobs.json --include-non-ai
```

Import `jobs.json` using **Import jobs** in the platform. The JSON is shaped as `{ "generated_at": "…", "count": 0, "jobs": [], "errors": [] }`.

## Configure public sources

Add objects to `boards.json` with an ATS type, its public board identifier, and a display name:

```json
[
  {"ats": "greenhouse", "board": "company-board-token", "company": "Company"},
  {"ats": "lever", "board": "company-site-name", "company": "Company"},
  {"ats": "ashby", "board": "company-board-name", "company": "Company"}
]
```

Board identifiers are the public slugs used in the employer's hosted career page. The collector does not bypass logins or access controls. Some boards may be inactive, renamed, rate-limited, or unavailable; failures are listed in the output's `errors` array and printed to stderr. Respect each employer's terms and rate limits before increasing crawl frequency.

`sources.json` accepts JobTech/Arbetsförmedlingen searches, for example:

```json
[
  {"ats":"jobtech", "source_id":"se-ai", "provider":"JobTech", "query":"AI", "limit":50, "max_pages":2}
]
```

It also accepts USAJOBS searches. Set `USAJOBS_API_KEY` and `USAJOBS_USER_AGENT` in the environment before configuring `{ "ats":"usajobs", "query":"AI software" }`. Do not commit API credentials. Country-specific services, aggregators, and commercial job boards often impose different API, attribution, caching, and redistribution rules; add each connector only after checking its official terms. This collector intentionally does not scrape search-engine result pages or bypass access controls.

## Refresh on a schedule

For a local data refresh, schedule the command with your OS task scheduler and keep the output file available for import. The hosted site is a static alpha: it does not run a background scraper, shared database, sign-in, payments, or employer self-service yet. The marketplace architecture and launch roadmap are in `docs/`; these product capabilities need a server-backed application before paid job posting can be offered.

## Matching signals

The scraper detects terms such as GitHub Copilot, Cursor, Claude Code, AI agents, AI-assisted / AI-native engineering, generative AI, LLMs, and AI code review. Its match score is a transparent keyword heuristic, not a hiring probability or endorsement. Check the original employer posting for current details and apply there.

## Backend foundation

See [`backend/README.md`](backend/README.md) for the API routes, database migration, required runtime settings, and deployment gates. Run focused checks with:

```bash
node --check backend/worker.mjs
node backend/worker.test.mjs
```

The Worker and schema are implementation foundations only; they are not connected to the current hosted static Site. Do not accept live employer payments until the Worker, database, trusted sign-in, Stripe webhook, moderation access, and actual package prices are configured and verified.
