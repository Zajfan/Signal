#!/usr/bin/env python3
"""Collect public job listings from Greenhouse, Lever, and Ashby job boards."""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import sys
import time
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
    "workflow": ["ai-assisted", "ai augmented", "ai-augmented", "ai-native", "ai first", "ai-first", "ai-powered development", "vibe coding"],
    "review": ["code review", "review generated code", "code quality"],
}
AI_SIGNAL_TERMS = tuple(term for values in AI_TERMS.values() for term in values) + (
    "artificial intelligence", "machine learning", "generative ai", "llm", "large language model",
)


def plain(value: object) -> str:
    value = str(value or "")
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def fetch_json(url: str) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
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
    kind, token = board["ats"].lower(), board["board"]
    company = board.get("company") or token
    if kind == "greenhouse":
        data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(token)}/jobs?content=true")
        raw_jobs = data.get("jobs", [])
    elif kind == "lever":
        raw_jobs = fetch_json(f"https://api.lever.co/v0/postings/{urllib.parse.quote(token)}?mode=json")
    elif kind == "ashby":
        data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(token)}?includeCompensation=true")
        raw_jobs = data.get("jobs", [])
    else:
        raise ValueError(f"Unsupported ATS '{kind}'. Use greenhouse, lever, or ashby.")
    return [normalize(kind, company, token, raw) for raw in raw_jobs]


def normalize(kind: str, company: str, board: str, raw: dict) -> dict:
    if kind == "greenhouse":
        title, loc = raw.get("title"), (raw.get("location") or {}).get("name", "")
        url, date = raw.get("absolute_url", ""), raw.get("updated_at") or raw.get("first_published")
        description = plain(raw.get("content", ""))
        departments = [x.get("name", "") for x in raw.get("departments", [])]
        offices = [x.get("name", "") for x in raw.get("offices", [])]
        extra = " ".join(departments + offices)
        salary_min = salary_max = None
    elif kind == "lever":
        title, loc = raw.get("text"), ((raw.get("categories") or {}).get("location") or "")
        url, date = raw.get("hostedUrl", ""), raw.get("createdAt")
        description = plain(" ".join([raw.get("description", ""), raw.get("descriptionPlain", ""), raw.get("additional", "")]))
        cats = raw.get("categories") or {}
        extra = " ".join(str(cats.get(k, "")) for k in ("team", "department", "commitment", "workplaceType"))
        salary = (raw.get("salaryRange") or {})
        salary_min, salary_max = clean_salary(salary.get("min")), clean_salary(salary.get("max"))
    else:
        title, loc = raw.get("title"), raw.get("location", "")
        url, date = raw.get("jobUrl", ""), raw.get("publishedAt")
        description = plain(" ".join([raw.get("descriptionPlain", ""), raw.get("descriptionHtml", "")]))
        extra = " ".join(str(x) for x in raw.get("employmentType", []) if x)
        comp = raw.get("compensation") or {}
        salary_min = clean_salary(comp.get("minValue"))
        salary_max = clean_salary(comp.get("maxValue"))
    title = plain(title)
    loc = plain(loc)
    text = f"{title} {description} {extra}".lower()
    matched = [label for label, terms in AI_TERMS.items() if any(term in text for term in terms)]
    signals = [term for term in AI_SIGNAL_TERMS if term in text]
    is_ai = bool(signals)
    score = min(99, 66 + len(set(signals)) * 4 + (8 if any(t in text for t in ("copilot", "cursor", "claude code", "ai-assisted", "ai-native")) else 0))
    lower_loc = loc.lower()
    work_mode = "Remote" if "remote" in lower_loc or "remote" in text[:500] else "Hybrid" if "hybrid" in lower_loc or "hybrid" in text[:500] else "On-site"
    level_patterns = {"Lead": r"principal|staff|lead", "Senior": r"senior|sr\.?", "Mid": r"mid.?level|intermediate", "Entry": r"junior|entry.?level|graduate"}
    level = next((x for x in ("Lead", "Senior", "Mid", "Entry") if re.search(rf"\b(?:{level_patterns[x]})\b", title.lower())), "Any level")
    stable_id = f"{kind}:{board}:{raw.get('id') or raw.get('gh_jid') or url}"
    tags = []
    for label, terms in AI_TERMS.items():
        if any(term in text for term in terms):
            tags.append({"copilot": "Copilot", "cursor": "Cursor", "claude code": "Claude Code", "agent": "AI agents", "workflow": "AI workflow", "review": "Code review"}[label])
    return {
        "id": stable_id, "title": title, "company": company, "location": loc or "Location not listed",
        "work_mode": work_mode, "level": level, "type": "Full-time", "salary_min": salary_min,
        "salary_max": salary_max, "posted_at": date_iso(date), "url": url,
        "description": description[:5000], "tags": tags, "focus": matched,
        "ai_explicit": is_ai, "match": score, "source": kind, "board": board,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--boards", default="boards.json", help="JSON file with public ATS board identifiers")
    parser.add_argument("--out", default="jobs.json", help="Output JSON path (default: jobs.json)")
    parser.add_argument("--workers", type=int, default=5, help="Concurrent board fetches (default: 5)")
    parser.add_argument("--include-non-ai", action="store_true", help="Include every software role, not only AI-signal roles")
    args = parser.parse_args()
    try:
        boards = json.loads(Path(args.boards).read_text(encoding="utf-8"))
        if not isinstance(boards, list):
            raise ValueError("boards.json must contain a JSON array")
        jobs, errors = [], []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(args.workers, 12))) as pool:
            futures = {pool.submit(source_jobs, board): board for board in boards}
            for future in concurrent.futures.as_completed(futures):
                board = futures[future]
                try:
                    result = future.result()
                    jobs.extend(result)
                    print(f"✓ {board.get('company', board.get('board'))}: {len(result)} openings", file=sys.stderr)
                except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as exc:
                    errors.append({"board": board, "error": str(exc)})
                    print(f"! {board.get('company', board.get('board'))}: {exc}", file=sys.stderr)
        if not args.include_non_ai:
            jobs = [j for j in jobs if j["ai_explicit"]]
        unique = {j["id"]: j for j in jobs if j["title"] and j["url"]}
        output = {"generated_at": datetime.now(timezone.utc).isoformat(), "count": len(unique), "jobs": sorted(unique.values(), key=lambda j: (j["posted_at"], j["match"]), reverse=True), "errors": errors}
        Path(args.out).write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {len(unique)} AI-signal roles to {args.out} ({len(errors)} board errors).", file=sys.stderr)
        return 0 if unique or not boards else 1
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Scraper error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
