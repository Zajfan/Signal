# Job source policy and coverage plan

**Version:** 0.0.2 (early alpha)

Signal should grow through dependable, documented coverage. “Global” is a coverage goal, not permission to copy every site. Use a source only when the source's API, license, contract or clear public-feed terms permit the intended display and outbound referral.

## Source classes

| Class | Examples | Intake rule |
|---|---|---|
| Public employment-service API/open data | Arbetsförmedlingen JobAd Links / JobSearch / JobStream; USAJOBS after API-key approval | Follow the API contract, license, rate limit, source labels and application-link rules. Record the terms/version checked. |
| Public ATS board | Greenhouse, Lever, Ashby | Use the documented public jobs feed for a known employer board; do not guess board IDs at scale. Keep the canonical employer/apply URL. |
| Employer-authorized feed | XML, JSON, ATS export, direct integration | Require proof of employer authority and a feed agreement or confirmation describing permitted fields and refresh cadence. |
| Licensed aggregation partner | Commercial job-data vendors and distribution networks | Contract must permit display, storage duration, linking, monetization and AI-job classification. Respect partner click attribution. |
| Direct paid employer post | Signal employer dashboard | Verify company/poster authority, collect payment for the selected package, review content, and manage expiry. |
| Unapproved/unclear site | Login-only boards, blocked pages, unknown reuse terms | Do not ingest until permission or a supported API/partner route is established. |

## Verified initial sources

### Sweden: Arbetsförmedlingen / JobTech

- **JobAd Links** is described by Arbetsförmedlingen as a public search API with full-text search and filters, for current and historical ads shared into the JobAd Links dataset. Its data page lists CC0, public access and no API key/registration. Its dataset description says the records are metadata and links supplied by job boards; preserve the original job-board link and attribution. [Service page](https://data.arbetsformedlingen.se/dataservice/jobad-links/) · [Dataset page](https://data.arbetsformedlingen.se/dataset/jobad-links/)
- **JobSearch/JobStream** provide access to ads published through Platsbanken; the service pages list public access and CC0/no key. Use JobSearch for query-based indexing and assess JobStream as the incremental refresh path after checking its current API specification. [JobSearch](https://data.arbetsformedlingen.se/dataservice/data-service-jobsearch/) · [JobStream](https://data.arbetsformedlingen.se/dataservice/jobstream/)
- **Posting into Platsbanken** is a separate partner integration. The Direct Transferred Job Posting API requires registration, an employer account and compliance with the advertising terms. Do not advertise Signal as an approved posting partner until that process is complete. [Partner API](https://data.arbetsformedlingen.se/dataservice/direct-transferred-job-posting-api/)
- The Agency distinguishes open public data from authenticated partner APIs; access to the latter requires a relationship and credentials. [API access guidance](https://arbetsformedlingen.se/other-languages/english-engelska/about-the-website/apis-and-open-data)

### United States: USAJOBS

USAJOBS documents its Job Search API for commercial job boards, mobile applications and social media sites. It returns currently open announcements, requires an API key, and specifies `Host`, `User-Agent` and `Authorization-Key` headers. Apply for a key and follow its rate limits and terms before enabling the connector. [Search API](https://developer.usajobs.gov/api-reference/get-api-search) · [Authentication](https://developer.usajobs.gov/Guides/Authentication) · [Rate limiting](https://developer.usajobs.gov/Guides/Rate-Limiting) · [Terms](https://developer.usajobs.gov/Guides/Terms-of-Service)

### ATS feeds

- [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html) documents public job-board GET endpoints; application submission is separately authenticated.
- [Lever postings API](https://github.com/lever/postings-api) is the public postings interface; confirm current documentation/terms during connector implementation.
- [Ashby Job Postings API](https://developers.ashbyhq.com/docs/public-job-posting-api) returns currently published postings for an organization's board and can include compensation. Respect `isListed` and only publish jobs intended for the public board.

### Europe-wide and other markets

- **EURES** could materially expand European coverage, but its portal states that only EURES partner organisations recognized by a National Coordination Office may extract data using its API or similar technologies. Seek an eligible partnership; do not build an unofficial scraper against the portal. [EURES portal notice](https://europa.eu/eures/portal/jv-se/home?lang=en&pageCode=find_a_job)
- For other public employment services, add country connectors only after checking primary documentation, licensing, application-link behavior and access limits. The source roadmap should prioritize official APIs and authorized job feeds before vendor or ATS expansion.
- Commercial aggregators can accelerate coverage, but their contract must explicitly permit redistribution on a paid job board and disclose their click-through/attribution requirements.

## Source registry contract

Each source entry should have:

- stable `source_id`, provider name, country/coverage, adapter type and enabled state;
- canonical API/feed URL, auth reference name (never the secret), official docs URL and last terms review;
- permission basis/license, allowed fields, required attribution, retention rules, click tracking and permitted monetization;
- employer/board identity and the proof or method used to validate that identity;
- polling schedule, concurrency/rate limit, last success, error state and last indexed cursor;
- owner/contact and a takedown route.

Each imported job must retain `source_id`, source job ID, original page URL, apply URL, first/last seen, source update/expiry time, content hash, permission class, and fields omitted by policy. Keep raw payloads only when the source agreement permits it.

## Ingestion lifecycle

1. Discover or receive a source and record permission before fetching.
2. Fetch within the source's documented limits; use conditional requests/cursors when available.
3. Normalize fields and language/country/currency with the source untouched in a provenance record.
4. Detect duplicates by source ID first, then employer + canonical URL and a conservative title/location fingerprint.
5. Classify job family and AI-tool use separately; retain the evidence snippets/terms that informed the classification.
6. Check the original posting and apply path; mark uncertain or suspicious records for review.
7. Recheck open status and source freshness. Expire, hide or tombstone closed/removed listings and remove content on valid takedown.
8. Report source attribution and send the candidate to the original application page unless the employer chose Signal-hosted applications.

## Expansion order

1. Make the confirmed Sweden APIs a stable, tested source connector.
2. Apply for USAJOBS API access; then add the source connector.
3. Add more employer-provided public-board tokens across Greenhouse, Lever and Ashby, with explicit registry approval.
4. Add source adapters only from official or contracted documentation (for example SmartRecruiters, Workday, Personio, Recruitee and other ATS providers after endpoint/terms verification).
5. Negotiate distribution partnerships for EURES, national boards and global aggregators where required.
6. Add a bounded career-page discovery crawler for employer domains that have been approved for discovery; honor robots directives, identify source terms, and route unknowns to human review rather than automatically copying listings.

“More sources” must improve real, current coverage—not inflate a count with reposts, stale ads or scraped copies that cannot legally be redistributed.
