# Signal Jobs

Signal Jobs is a focused job discovery board for software developers who build with AI. It combines a simple public ATS scraper with a searchable listings interface, saved jobs, filters, and JSON import.

## What's here

- `index.html` — responsive listings platform. Saved jobs and imported listings persist in this browser.
- `scraper.py` — dependency-free Python collector for public Greenhouse, Lever, and Ashby job boards.
- `boards.json` — editable sample board configuration.

The six listings shown before importing are illustrative preview records, not verified current openings. The scraper reads live public ATS feeds when you run it and writes the resulting records to `jobs.json`.

## Run a scrape

Python 3.10+ is recommended. No pip packages are required.

```bash
python3 scraper.py --boards boards.json --out jobs.json
```

By default, the scraper keeps jobs whose descriptions contain AI development signals. Include all jobs from configured boards with:

```bash
python3 scraper.py --boards boards.json --out jobs.json --include-non-ai
```

Import `jobs.json` using **Import jobs** in the platform. The JSON is shaped as `{ "generated_at": "…", "count": 0, "jobs": [], "errors": [] }`.

## Configure company boards

Add objects to `boards.json` with an ATS type, its public board identifier, and a display name:

```json
[
  {"ats": "greenhouse", "board": "company-board-token", "company": "Company"},
  {"ats": "lever", "board": "company-site-name", "company": "Company"},
  {"ats": "ashby", "board": "company-board-name", "company": "Company"}
]
```

Board identifiers are the public slugs used in the employer's hosted career page. The collector does not bypass logins or access controls. Some boards may be inactive, renamed, rate-limited, or unavailable; failures are listed in the output's `errors` array and printed to stderr. Respect each employer's terms and rate limits before increasing crawl frequency.

## Refresh on a schedule

For a personal data refresh, schedule the command with your OS task scheduler (for example, a daily cron job) and keep the output file available for import. The hosted site is static: it does not run a background scraper or publish newly scraped data automatically. A later server-backed version can add scheduled ingestion, durable shared storage, and alerts.

## Matching signals

The scraper detects terms such as GitHub Copilot, Cursor, Claude Code, AI agents, AI-assisted / AI-native engineering, generative AI, LLMs, and AI code review. Its match score is a transparent keyword heuristic, not a hiring probability or endorsement. Check the original employer posting for current details and apply there.
