#!/usr/bin/env python3
"""Collect public job listings from Greenhouse, Lever, and Ashby job boards."""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = "SignalJobsBot/0.1 (+public ATS job board collector)"
AI_TERMS = {
    "copilot": ["github copilot", "copilot"],
    "cursor": ["cursor"],
    "claude code": ["claude code"],
    "agent": ["ai agent", "agentic", "coding agent", "software agent"],
"workflow": ["ai-assisted", "ai assisted", "ai augmented", "ai-augmented", "ai-native", "ai native", "ai first", "ai-first", "ai-powered development", "vibe coding"],
    "review": ["code review", "review generated code", "code quality"],
    "machine learning": ["machine learning", "ml engineer", "machine-learning", "maskininlärning", "maskinlärning"],
"genai": ["generative ai", "generativ ai", "genai", "llm", "large language model", "språkmodell", "ai engineer", "ai software", "ai developer"],
    "ai platform": ["ai infrastructure", "ai platform", "model serving", "mlops", "ml ops"],
    "research": ["ai researcher", "ai research", "machine learning researcher"],
}
AI_SIGNAL_TERMS = tuple(term for values in AI_TERMS.values() for term in values) + ("artificial intelligence", "artificiell intelligens")


def plain(value: object) -> str:
    value = str(value or "")
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def fetch_json(url: str, headers: dict[str, str] | None = None) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=25) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def clean_salary(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    match = re.search(r"(?:USD\s*)?\$?\s*([\d,]+(?:\.\d+)?)\s*([kK])?", str(value))
    if not match:
        return None
    number = float(match.group(1).replace(",", ""))
    return int(number * (1000 if match.group(2) else 1))


def date_iso(value: object) -> str:
    if not value:
        return ""
    raw = str(value)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).date().isoformat()
    except ValueError:
        return raw[:10] if re.match(r"\d{4}-\d{2}-\d{2}", raw) else ""


def source_jobs(board: dict) -> list[dict]:
    kind = (board.get("ats") or board.get("type") or "").lower()
    token = board.get("board") or board.get("source_id") or kind
    company = board.get("company") or board.get("provider") or token
    if kind in ("jobtech", "arbetsformedlingen"):
        endpoint = board.get("endpoint", "https://jobsearch.api.jobtechdev.se/search")
        query = board.get("query", "AI")
        limit = max(1, min(int(board.get("limit", 50)), 100))
        max_pages = max(1, min(int(board.get("max_pages", 2)), 20))
        rows = []
        for page in range(max_pages):
            params = urllib.parse.urlencode({"q": query, "limit": limit, "offset": page * limit})
            result = fetch_json(f"{endpoint}?{params}")
            hits = result.get("hits", [])
            rows.extend(normalize("jobtech", company, token, raw) for raw in hits)
            if len(hits) < limit:
                break
        return rows
    if kind == "usajobs":
        api_key = os.getenv("USAJOBS_API_KEY")
        user_agent = os.getenv("USAJOBS_USER_AGENT")
        if not api_key or not user_agent:
            raise ValueError("USAJOBS requires USAJOBS_API_KEY and USAJOBS_USER_AGENT; see README.md")
        params = {"Keyword": board.get("query", "AI software"), "ResultsPerPage": max(1, min(int(board.get("limit", 100)), 500)), "Fields": "Full"}
        for key in ("LocationName", "DatePosted", "RemoteIndicator", "WhoMayApply"):
            if board.get(key) is not None:
                params[key] = str(board[key])
        headers = {"Host": "data.usajobs.gov", "User-Agent": user_agent, "Authorization-Key": api_key}
        result = fetch_json("https://data.usajobs.gov/api/Search?" + urllib.parse.urlencode(params), headers=headers)
        hits = (result.get("SearchResult") or {}).get("SearchResultItems", [])
        return [normalize("usajobs", company, token, raw) for raw in hits]
    if kind == "greenhouse":
        data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(token)}/jobs?content=true")
        raw_jobs = data.get("jobs", [])
    elif kind == "lever":
        raw_jobs = fetch_json(f"https://api.lever.co/v0/postings/{urllib.parse.quote(token)}?mode=json")
    elif kind == "ashby":
        data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(token)}?includeCompensation=true")
        raw_jobs = data.get("jobs", [])
    else:
        raise ValueError(f"Unsupported source '{kind}'. Supported: greenhouse, lever, ashby, jobtech, usajobs.")
    return [normalize(kind, company, token, raw) for raw in raw_jobs]


def normalize(kind: str, company: str, board: str, raw: dict) -> dict:
    currency = None
    if kind == "jobtech":
        title = raw.get("headline", "")
        employer = raw.get("employer") or {}
        company = employer.get("name") or company
        address = raw.get("workplace_address") or {}
        location = [address.get(k) for k in ("city", "municipality", "region", "country") if address.get(k)]
        loc = ", ".join(dict.fromkeys(location))
        url = raw.get("webpage_url", "")
        source_url = url
        date = raw.get("publication_date") or raw.get("last_publication_date")
        desc = raw.get("description") or {}
        description = plain(desc.get("text") or desc.get("text_formatted") or "")
        employment = raw.get("employment_type") or {}
        extra = " ".join([str(employment.get("label", "")), str((raw.get("occupation") or {}).get("label", "")), str((raw.get("occupation_field") or {}).get("label", ""))])
        salary_min = salary_max = None
        job_type = "Contract" if any(x in extra.lower() for x in ("contract", "tidsbegränsad", "project")) else "Full-time"
        work_model = str(raw.get("workplace_model") or "")
    elif kind == "usajobs":
        detail = raw.get("MatchedObjectDescriptor") or {}
        title = detail.get("PositionTitle", "")
        company = detail.get("OrganizationName") or detail.get("DepartmentName") or company
        loc = detail.get("PositionLocationDisplay", "")
        url = (detail.get("ApplyURI") or [detail.get("PositionURI", "")])[0]
        source_url = detail.get("PositionURI", url)
        date = detail.get("PublicationStartDate")
        details = (detail.get("UserArea") or {}).get("Details") or {}
        description = plain(" ".join([details.get("JobSummary", ""), details.get("MajorDuties", ""), detail.get("QualificationSummary", "")]))
        extra = " ".join(x.get("Name", "") for x in detail.get("JobCategory", []))
        remuneration = detail.get("PositionRemuneration") or []
        salary_min = clean_salary(remuneration[0].get("MinimumRange")) if remuneration else None
        salary_max = clean_salary(remuneration[0].get("MaximumRange")) if remuneration else None
        job_type = "Full-time" if any("full" in x.get("Name", "").lower() for x in detail.get("PositionSchedule", [])) else "Contract"
        work_model = ""
        currency = "USD"
    elif kind == "greenhouse":
        title, loc = raw.get("title"), (raw.get("location") or {}).get("name", "")
        url, date = raw.get("absolute_url", ""), raw.get("updated_at") or raw.get("first_published")
        source_url = url
        description = plain(raw.get("content", ""))
        departments = [x.get("name", "") for x in raw.get("departments", [])]
        offices = [x.get("name", "") for x in raw.get("offices", [])]
        extra = " ".join(departments + offices)
        salary_min = salary_max = None
        job_type = "Full-time"
        work_model = ""
    elif kind == "lever":
        title, loc = raw.get("text"), ((raw.get("categories") or {}).get("location") or "")
        url, date = raw.get("hostedUrl", ""), raw.get("createdAt")
        source_url = url
        description = plain(" ".join([raw.get("description", ""), raw.get("descriptionPlain", ""), raw.get("additional", "")]))
        cats = raw.get("categories") or {}
        extra = " ".join(str(cats.get(k, "")) for k in ("team", "department", "commitment", "workplaceType"))
        salary = (raw.get("salaryRange") or {})
        salary_min, salary_max = clean_salary(salary.get("min")), clean_salary(salary.get("max"))
        job_type = "Contract" if "contract" in extra.lower() else "Full-time"
        work_model = str((raw.get("categories") or {}).get("workplaceType", ""))
    else:
        title, loc = raw.get("title"), raw.get("location", "")
        url, date = raw.get("jobUrl", ""), raw.get("publishedAt")
        source_url = url
        description = plain(" ".join([raw.get("descriptionPlain", ""), raw.get("descriptionHtml", "")]))
        employment_type = raw.get("employmentType", [])
        extra = str(employment_type) if isinstance(employment_type, str) else " ".join(str(x) for x in employment_type if x)
        comp = raw.get("compensation") or {}
        salary_min = clean_salary(comp.get("minValue"))
        salary_max = clean_salary(comp.get("maxValue"))
        job_type = "Contract" if "contract" in extra.lower() else "Full-time"
        work_model = str(raw.get("workplaceType", ""))
    title = plain(title)
    loc = plain(loc)
    text = f"{title} {description} {extra}".lower()
    matched = [label for label, terms in AI_TERMS.items() if any(term in text for term in terms)]
    signals = [term for term in AI_SIGNAL_TERMS if term in text]
    is_ai = bool(signals)
    score = min(99, 66 + len(set(signals)) * 4 + (8 if any(t in text for t in ("copilot", "cursor", "claude code", "ai-assisted", "ai-native")) else 0))
    model = f"{work_model} {loc} {text[:500]}".lower()
    work_mode = "Remote" if any(x in model for x in ("remote", "distans", "fully distributed")) else "Hybrid" if any(x in model for x in ("hybrid", "hybridarbete")) else "On-site"
    level_patterns = {"Lead": r"principal|staff|lead", "Senior": r"senior|sr\.?", "Mid": r"mid.?level|intermediate", "Entry": r"junior|entry.?level|graduate"}
    level = next((x for x in ("Lead", "Senior", "Mid", "Entry") if re.search(rf"\b(?:{level_patterns[x]})\b", title.lower())), "Any level")
    stable_id = f"{kind}:{board}:{raw.get('id') or raw.get('gh_jid') or raw.get('MatchedObjectId') or url}"
    tags = []
    for label, terms in AI_TERMS.items():
        if any(term in text for term in terms):
            labels = {"copilot": "Copilot", "cursor": "Cursor", "claude code": "Claude Code", "agent": "AI agents", "workflow": "AI workflow", "review": "Code review", "machine learning": "Machine learning", "genai": "Generative AI", "ai platform": "AI infrastructure", "research": "AI research"}
            tags.append(labels[label])
    return {
        "id": stable_id, "title": title, "company": company, "location": loc or "Location not listed",
        "work_mode": work_mode, "level": level, "type": job_type, "salary_min": salary_min,
        "salary_max": salary_max, "posted_at": date_iso(date), "url": url,
        "description": description[:5000], "tags": tags, "focus": matched,
        "ai_explicit": is_ai, "match": score, "source": kind, "board": board, "source_url": source_url,
        "currency": currency,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boards", default="boards.json", help="JSON file with public ATS board identifiers")
    parser.add_argument("--sources", default="sources.json", help="JSON file with public employment-service or API sources")
    parser.add_argument("--out", default="jobs.json", help="Output JSON path (default: jobs.json)")
    parser.add_argument("--workers", type=int, default=5, help="Concurrent board fetches (default: 5)")
    parser.add_argument("--include-non-ai", action="store_true", help="Include every software role, not only AI-signal roles")
    args = parser.parse_args()
    try:
        boards = json.loads(Path(args.boards).read_text(encoding="utf-8")) if Path(args.boards).exists() else []
        sources = json.loads(Path(args.sources).read_text(encoding="utf-8")) if Path(args.sources).exists() else []
        if not isinstance(boards, list) or not isinstance(sources, list):
            raise ValueError("boards.json must contain a JSON array")
        configs = boards + sources
        if not configs:
            raise ValueError("No sources configured in boards.json or sources.json")
        jobs, errors = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
            futures = {pool.submit(source_jobs, board): board for board in configs}
            for future in concurrent.futures.as_completed(futures):
                board = futures[future]
                try:
                    result = future.result()
                    jobs.extend(result)
                    print(f"✓ {board.get('company', board.get('provider', board.get('board', board.get('source_id'))))}: {len(result)} openings", file=sys.stderr)
                except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    errors.append({"source": board, "error": str(exc)})
                    print(f"! {board.get('company', board.get('provider', board.get('board', board.get('source_id'))))}: {exc}", file=sys.stderr)
        if not args.include_non_ai:
            jobs = [j for j in jobs if j["ai_explicit"]]
        unique = {j["id"]: j for j in jobs if j["title"] and j["url"]}
        output = {"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(unique), "jobs": sorted(unique.values(), key=lambda j: (j["posted_at"], j["match"]), reverse=True), "errors": errors}
        Path(args.out).write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {len(unique)} AI-signal roles to {args.out} ({len(errors)} board errors).", file=sys.stderr)
        return 0 if unique or not configs else 1
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Scraper error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
