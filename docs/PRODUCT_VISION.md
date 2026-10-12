# Signal — Product vision

**Product:** Signal AI Jobs  
**Version:** 0.0.4 (local alpha)
**Purpose:** Build the trusted global job marketplace for work building, deploying, and working effectively with AI.

## What Signal is

Signal is a two-sided jobs marketplace:

- Job seekers search global AI roles for free, save openings, and follow the employer's application route.
- Employers create a verified company profile, publish real vacancies, pay for a listing or promotion, and measure listing performance.
- Signal brings in additional openings from public employment services, approved ATS feeds, and licensed data partners. Imported jobs link clearly to their original source.

The initial focus includes both **AI engineering work** (machine learning, applied AI, LLMs, agents, data and infrastructure) and **software roles where AI-assisted development is a stated part of the job** (Copilot, Cursor, Claude Code, agent workflows, AI code review and AI-first delivery). These are separate classifications and filters.

## Product promise

Help people find credible AI work, and help companies reach people who know how to build with AI. Every listing should say who is hiring, where the work can be done, when it was checked, where to apply, and whether it is paid or imported.

## Marketplace participants

### Job seekers

- Search by role, skill, employer, location and work arrangement.
- Filter by job family, seniority, contract type, salary range/currency, language and work authorization when supplied.
- See when a job was first found and last confirmed open, with a direct apply link and source label.
- Save jobs and create alerts after signing in; browsing stays open without an account.
- Report an expired, misleading or suspicious listing.

### Employers

- Register and verify a company and an authorized representative.
- Create a job, preview the public listing, select a posting package, pay, and submit for review.
- Edit, pause, renew and close listings from a company dashboard.
- View impressions, clicks and attributed application handoffs.
- In a later milestone, connect an ATS, bulk-upload listings or distribute an employer's jobs to approved partners.

### Signal operations

- Review employer identity and job submissions before publication.
- Monitor data-source health, source permissions, update lag, duplicates and takedown requests.
- Detect fraud, expired postings, salary inconsistencies and AI keyword stuffing.
- Keep an audit record of moderation, payment and source changes.

## Listing classes and disclosure

1. **Employer-posted:** Created by an employer in Signal. May be organic or sponsored; sponsored placement is always labeled.
2. **Official/public-service feed:** Sourced from a public employment service. Retain the required source and apply links.
3. **ATS/company career feed:** Reproduced only within the feed's documented use and content terms; link to the employer's original page.
4. **Licensed partner feed:** Governed by a written data and distribution agreement.

Imported jobs are not sold as Signal's own listings. Paid placement applies to employer-authorized Signal posts and explicitly permitted sponsored campaigns.

## Revenue model — proposal, prices not set

- One-time standard job post.
- Optional featured placement with a fixed, disclosed duration.
- Multi-post credits for repeat employers.
- Later: company subscription for ATS sync, team seats, analytics and job distribution.

The launch price, duration, currencies, tax handling, refunds and promotion rules are decisions to confirm before real checkout is enabled. The platform must never present a draft price as an active offer.

## Trust requirements

- No fabricated employer names or current openings in production data.
- Every opening has a working apply route and visible source/provenance.
- Validate the hiring company and an authorized poster; moderate the vacancy before publication.
- Expire or remove closed jobs promptly and honour source takedowns.
- Keep sponsored placements visually distinct from relevance-ranked results.
- Do not score candidates or infer protected traits. Explain job relevance signals in ordinary terms.
- Minimize applicant personal data; the early marketplace should link to employer applications rather than collect CVs.

## Success measures

- Verified, current AI listings and source coverage by country/job family.
- Time from source publication to Signal visibility and time to remove a closed listing.
- Search-to-job-detail and job-detail-to-apply click-through.
- Employer activation: verified company → paid post → approved listing.
- Employer renewal/repurchase and candidate return/alert engagement.
- Duplicate, expired, misleading and disputed listing rates.

## Current boundary

The repository now runs a local SQLite-backed marketplace with employer drafts, simulated checkout, company/job review, source ingestion/review and candidate search/detail pages. A separate Python/Gunicorn runtime supports public browsing on the owner's own machine, with `signal.tnhc.dev` as the intended domain. Local identity controls remain development tools; real authentication, merchant configuration, public-domain routing and launch operations remain unconfigured. The partner program is planned in the roadmap.
