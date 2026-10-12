#!/usr/bin/env python3
"""Collect public job listings from supported ATS and attributed public feeds."""
from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

UA = "SignalJobsBot/0.1 (+public ATS job board collector)"
_REQUEST_LOCK = threading.Lock()
_REQUEST_STARTS: dict[str, float] = {}
MAX_RETRY_DELAY = 60
AI_TERMS = {
    "copilot": ["github copilot", "copilot"],
    "cursor": ["cursor"],
    "claude code": ["claude code"],
    "agent": ["ai agent", "agentic", "coding agent", "software agent"],
"workflow": ["ai-assisted", "ai assisted", "ai augmented", "ai-augmented", "ai-native", "ai native", "ai first", "ai-first", "ai-powered development", "vibe coding"],
    "review": ["ai code review", "review generated code", "ai-generated code"],
    "machine learning": ["machine learning", "ml engineer", "machine-learning", "maskininlärning", "maskinlärning"],
"genai": ["generative ai", "generativ ai", "genai", "llm", "large language model", "språkmodell", "ai engineer", "ai software", "ai developer"],
    "ai platform": ["ai infrastructure", "ai platform", "model serving", "mlops", "ml ops"],
    "research": ["ai researcher", "ai research", "machine learning researcher"],
}
AI_SIGNAL_TERMS = tuple(term for values in AI_TERMS.values() for term in values) + ("artificial intelligence", "artificiell intelligens")

# Unrecognized or multi-country restrictions retain their full location text.
# A country is assigned only for an exact, single-country match.
COUNTRY_NAMES = {
    "united states": "US", "united states of america": "US", "usa": "US", "us": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB", "canada": "CA",
    "australia": "AU", "new zealand": "NZ", "sweden": "SE", "norway": "NO",
    "denmark": "DK", "finland": "FI", "germany": "DE", "france": "FR", "spain": "ES",
    "italy": "IT", "ireland": "IE", "netherlands": "NL", "belgium": "BE", "poland": "PL",
    "portugal": "PT", "switzerland": "CH", "austria": "AT", "india": "IN", "singapore": "SG",
    "japan": "JP", "brazil": "BR", "mexico": "MX", "south africa": "ZA", "philippines": "PH",
    "argentina": "AR", "china": "CN", "colombia": "CO", "pakistan": "PK", "ukraine": "UA",
    "south korea": "KR", "republic of korea": "KR", "chile": "CL", "sri lanka": "LK",
    "indonesia": "ID", "nigeria": "NG", "costa rica": "CR", "romania": "RO", "greece": "GR",
    "czechia": "CZ", "czech republic": "CZ", "peru": "PE", "croatia": "HR", "georgia": "GE",
    "hong kong": "HK", "taiwan": "TW", "malaysia": "MY", "bulgaria": "BG", "serbia": "RS",
}


def has_term(text: str, term: str) -> bool:
    """Match terms in visible job text, without matching inside other words."""
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I) is not None


def timestamp_iso(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            dt = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc)
        elif isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError("Unsupported timestamp")
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (ValueError, OverflowError, OSError) as exc:
        raise ValueError("Invalid provider expiry timestamp") from exc


def restriction_country(value: str) -> str | None:
    country = value.strip()
    return COUNTRY_NAMES.get(country.lower()) or (country.upper() if country.upper() in COUNTRY_NAMES.values() else None)


def attributed_url(value: object, host: str) -> str:
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise ValueError("Provider listing URL is missing or invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        allowed_hosts = (host, "www." + host)
        if host == "arbeitnow.com":
            allowed_hosts += ("arbeitnow.ch", "www.arbeitnow.ch", "arbeitnow.co.uk", "www.arbeitnow.co.uk", "arbeitnow.fr", "www.arbeitnow.fr")
        valid = parsed.scheme == "https" and parsed.hostname in allowed_hosts and parsed.path not in ("", "/") and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except ValueError:
        valid = False
    if not valid:
        raise ValueError(f"Listing URL must point to {host} for attribution")
    return value


def feed_entries(data: object) -> list[dict]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list) or any(not isinstance(row, dict) for row in data["jobs"]):
        raise ValueError("Provider response must contain a jobs array of objects")
    return data["jobs"]


def feed_employment(value: object) -> str:
    raw = str(value or "").lower().replace("_", " ").replace("-", " ")
    return {"full time": "Full-time", "part time": "Part-time", "contractor": "Contract", "contract": "Contract",
            "freelance": "Freelance", "intern": "Internship", "internship": "Internship", "temporary": "Temporary",
            "volunteer": "Volunteer"}.get(raw, "Other")


def remotive_salary(value: object) -> tuple[int | None, int | None, str | None, str | None]:
    text = plain(value)
    code = re.search(r"\b(USD|EUR|GBP|CAD|AUD|NZD|INR|SEK|NOK|DKK|CHF|JPY|SGD)\b", text, re.I)
    currency = code.group().upper() if code else next((code for symbol, code in (("€", "EUR"), ("£", "GBP"), ("$", "USD")) if symbol in text), None)
    amounts = list(re.finditer(r"(?<![\w.])\d[\d,]*(?:\.\d+)?\s*[kK]?(?!\w)", text))
    if not currency or not amounts or len(amounts) > 2:
        return None, None, None, None
    numbers = []
    for amount in amounts:
        number = amount.group()
        # Compact amounts can use a decimal comma (35,3k); grouped amounts
        # use three digits after a comma (35,300).
        if re.fullmatch(r"\d+,\d{1,2}\s*[kK]", number):
            number = number.replace(",", ".")
        numbers.append(clean_salary(number))
    period = next((period for marker, period in (("hour", "hourly"), ("month", "monthly"), ("week", "weekly"), ("year", "annual"), ("annual", "annual")) if marker in text.lower()), None)
    range_text = text[amounts[0].end():amounts[1].start()] if len(amounts) == 2 else ""
    high = numbers[1] if len(numbers) == 2 and re.search(r"[-–—]|\bto\b", range_text, re.I) else None
    if high is not None and numbers[0] > high:
        return None, None, currency, period
    return numbers[0], high, currency, period


def plain(value: object) -> str:
    value = str(value or "")
    value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def fetch_json(url: str, headers: dict[str, str] | None = None) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    host = urllib.parse.urlsplit(url).hostname or ""
    # Remotive's provider-wide six-hour scheduler slot budgets one actual request.
    attempts = 1 if host in ("remotive.com", "www.remotive.com") else 3
    for attempt in range(attempts):
        # Serialize request start times across workers without holding a lock during IO.
        with _REQUEST_LOCK:
            clock = time.monotonic()
            if host in _REQUEST_STARTS:
                delay = max(0, .5 - (clock - _REQUEST_STARTS[host]))
                if delay:
                    time.sleep(delay)
            _REQUEST_STARTS[host] = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.loads(response.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            if attempt == attempts - 1 or (exc.code != 429 and not 500 <= exc.code <= 599):
                raise
            delay = .5 * (2 ** attempt)
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    try:
                        retry_date = parsedate_to_datetime(retry_after)
                        if retry_date.tzinfo is None:
                            retry_date = retry_date.replace(tzinfo=timezone.utc)
                        delay = max(0, (retry_date - datetime.now(timezone.utc)).total_seconds())
                    except (ValueError, TypeError, OverflowError):
                        raise exc
                # Never shorten a provider-requested wait and retry prematurely.
                if not 0 <= delay <= MAX_RETRY_DELAY:
                    raise
            exc.close()
            if delay:
                time.sleep(delay)


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
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc).date().isoformat()
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
    if kind == "himalayas":
        query = str(board.get("query") or "").strip()
        search = bool(query)
        base = "https://himalayas.app/jobs/api" + ("/search" if search else "")
        limit = max(1, min(int(board.get("limit", 20)), 20))
        max_pages = max(1, min(int(board.get("max_pages", 2)), 100))
        rows, cursors = {}, set()
        cursor = None
        for page in range(1, max_pages + 1):
            params = {"q": query, "page": page} if search else {"limit": limit}
            if cursor is not None:
                params["cursor"] = cursor
            data = fetch_json(base + "?" + urllib.parse.urlencode(params))
            entries = feed_entries(data)
            for raw in entries:
                row = normalize(kind, company, token, raw)
                rows[row["id"]] = row
            if not entries:
                break
            if search:
                total, page_size = data.get("totalCount"), data.get("limit")
                if type(total) is not int or total < 0 or type(page_size) is not int or page_size < 1:
                    raise ValueError("Himalayas search response has invalid totalCount or limit")
                if page * page_size >= total:
                    break
            else:
                cursor = data.get("nextCursor")
                if cursor is None or cursor == "":
                    break
                if not isinstance(cursor, str):
                    raise ValueError("Himalayas browse response has an invalid cursor")
                if cursor in cursors:
                    break
                cursors.add(cursor)
        return list(rows.values())
    if kind == "remotive":
        params = {}
        if board.get("query"):
            params["search"] = board["query"]
        if board.get("category"):
            params["category"] = board["category"]
        if board.get("limit") is not None:
            params["limit"] = max(1, min(int(board["limit"]), 1000))
        url = "https://remotive.com/api/remote-jobs"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        rows = [normalize(kind, company, token, raw) for raw in feed_entries(fetch_json(url))]
        return list({row["id"]: row for row in rows}.values())
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
    if kind == "smartrecruiters":
        base = f"https://api.smartrecruiters.com/v1/companies/{urllib.parse.quote(token, safe='')}/postings"
        limit = max(1, min(int(board.get("limit", 100)), 100))
        rows = []
        for page in range(max(1, min(int(board.get("max_pages", 20)), 100))):
            result = fetch_json(base + "?" + urllib.parse.urlencode({"limit": limit, "offset": page * limit}))
            entries = result.get("content", [])
            for entry in entries:
                detail = fetch_json(base + "/" + urllib.parse.quote(str(entry["id"]), safe=""))
                rows.append(normalize(kind, company, token, detail))
            if not entries or len(entries) < limit or (page + 1) * limit >= result.get("totalFound", 0):
                break
        return rows
    if kind == "recruitee":
        if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]*[a-zA-Z0-9])?", token):
            raise ValueError("Recruitee board must be a career-site subdomain")
        headers = {}
        if board.get("token_env"):
            secret = os.getenv(board["token_env"])
            if not secret: raise ValueError("Configured Recruitee token environment variable is missing")
            headers["X-Careers-Sites-Token"] = secret
        data = fetch_json(f"https://{token}.recruitee.com/api/offers", headers=headers)
        return [normalize(kind, company, token, raw) for raw in data.get("offers", [])]
    if kind == "jobicy":
        params = {}
        if board.get("query"):
            params["tag"] = board["query"]
        if board.get("location"):
            params["geo"] = board["location"]
        if board.get("industry"):
            params["industry"] = board["industry"]
        limit = max(1, min(int(board.get("limit", 50)), 100))
        params["count"] = limit
        max_pages = max(1, min(int(board.get("max_pages", 5)), 20))
        rows, cursors = {}, set()
        cursor = board.get("cursor")
        for page in range(max_pages):
            if cursor is not None:
                params["cursor"] = cursor
            url = "https://jobicy.com/api/v2/remote-jobs"
            if params:
                url += "?" + urllib.parse.urlencode(params)
            data = fetch_json(url)
            entries = feed_entries(data)
            for raw in entries:
                row = normalize(kind, company, token, raw)
                rows[row["id"]] = row
            if not entries:
                break
            cursor = data.get("nextCursor")
            if cursor is None or cursor == "":
                break
            if not isinstance(cursor, str):
                raise ValueError("Jobicy response has an invalid cursor")
            if cursor in cursors:
                break
            cursors.add(cursor)
        return list(rows.values())
    if kind == "remoteok":
        limit = max(1, min(int(board.get("limit", 100)), 500))
        url = "https://remoteok.com/api"
        data = fetch_json(url)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise ValueError("RemoteOK response must be an array of objects")
        entries = data[1:] if data and 'legal' in data[0] and 'id' not in data[0] else data
        query = str(board.get("query", "")).lower()
        if query:
            entries = [e for e in entries if query in str(e.get("position", "")).lower() or query in str(e.get("description", "")).lower() or any(query in str(t).lower() for t in e.get("tags", []))]
        rows = [normalize(kind, company, token, raw) for raw in entries]
        return list({row["id"]: row for row in rows[:limit]}.values())
    if kind == "arbeitnow":
        params = {}
        if board.get("query"):
            params["search"] = board["query"]
        if board.get("location"):
            params["location"] = board["location"]
        if board.get("tag"):
            params["tag"] = board["tag"]
        limit = max(1, min(int(board.get("limit", 100)), 500))
        max_pages = max(1, min(int(board.get("max_pages", 5)), 20))
        rows = {}
        for page in range(1, max_pages + 1):
            params["page"] = page
            url = "https://www.arbeitnow.com/api/job-board-api"
            if params:
                url += "?" + urllib.parse.urlencode(params)
            data = fetch_json(url)
            if not isinstance(data, dict) or not isinstance(data.get("data"), list) or any(not isinstance(row, dict) for row in data['data']):
                raise ValueError("Arbeitnow response must contain a data array of objects")
            entries = data['data']
            for raw in entries:
                row = normalize(kind, company, token, raw)
                rows[row['id']] = row
            if not entries or (isinstance(data.get('links'), dict) and data['links'].get('next') is None):
                break
            if len(rows) >= limit:
                break
        return list(rows.values())[:limit]
    if kind == "greenhouse":
        data = fetch_json(f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(token)}/jobs?content=true")
        raw_jobs = data.get("jobs", [])
    elif kind == "lever":
        host = "api.eu.lever.co" if board.get("region") == "eu" else "api.lever.co"
        raw_jobs = fetch_json(f"https://{host}/v0/postings/{urllib.parse.quote(token, safe='')}?mode=json")
    elif kind == "ashby":
        data = fetch_json(f"https://api.ashbyhq.com/posting-api/job-board/{urllib.parse.quote(token)}?includeCompensation=true")
        raw_jobs = data.get("jobs", [])
    else:
        raise ValueError(f"Unsupported source '{kind}'. Supported: greenhouse, lever, ashby, jobtech, usajobs, smartrecruiters, recruitee, himalayas, remotive, jobicy, remoteok, arbeitnow.")
    return [normalize(kind, company, token, raw) for raw in raw_jobs]


def normalize(kind: str, company: str, board: str, raw: dict) -> dict:
    currency = None
    country = None
    expires_at = None
    salary_period = None
    if kind == "himalayas":
        title = raw.get("title")
        company = raw.get("companyName") or company
        url = source_url = attributed_url(raw.get("guid"), "himalayas.app")
        countries = raw.get("locationRestrictions") or []
        timezones = raw.get("timezoneRestrictions") or []
        if not isinstance(countries, list) or not all(isinstance(item, str) for item in countries) or not isinstance(timezones, list):
            raise ValueError("Himalayas location restrictions must be arrays")
        countries = list(dict.fromkeys(item.strip() for item in countries if item.strip()))
        country = restriction_country(countries[0]) if len(countries) == 1 else None
        loc = ", ".join(countries)
        if timezones:
            zone_text = ", ".join("UTC" + ("+" if float(zone) >= 0 else "") + str(zone) for zone in timezones)
            loc = (loc + "; " if loc else "") + "Time zones: " + zone_text
        loc = loc or "Worldwide"
        date = raw.get("pubDate")
        expires_at = timestamp_iso(raw.get("expiryDate"))
        description = plain(raw.get("description", ""))
        extra = str(raw.get("employmentType") or "")
        job_type = feed_employment(extra)
        work_model = "remote"
        currency = raw.get("currency") or None
        salary_min, salary_max = clean_salary(raw.get("minSalary")), clean_salary(raw.get("maxSalary"))
        salary_period = raw.get("salaryPeriod") or "annual"
    elif kind == "remotive":
        if not isinstance(raw.get("id"), (str, int)) or isinstance(raw.get("id"), bool) or not str(raw["id"]).strip():
            raise ValueError("Remotive record requires a provider job ID")
        title = raw.get("title")
        company = raw.get("company_name") or company
        url = source_url = attributed_url(raw.get("url"), "remotive.com")
        loc = plain(raw.get("candidate_required_location")) or "Location not listed"
        country = restriction_country(loc)
        date = raw.get("publication_date")
        description = plain(raw.get("description", ""))
        extra = str(raw.get("job_type") or "")
        job_type = feed_employment(extra)
        work_model = "remote"
        salary_min, salary_max, currency, salary_period = remotive_salary(raw.get("salary"))
    elif kind in ("smartrecruiters", "recruitee"):
        if kind == "smartrecruiters":
            title = raw.get("name")
            company = (raw.get("company") or {}).get("name") or company
            address = raw.get("location") or {}
            loc = ", ".join(str(address.get(k)) for k in ("city", "region", "country") if address.get(k))
            country = address.get("country")
            url = raw.get("applyUrl", "")
            source_url = f"https://jobs.smartrecruiters.com/{urllib.parse.quote(board, safe='')}/{urllib.parse.quote(str(raw.get('id', '')), safe='')}"
            date = raw.get("releasedDate")
            description = plain(" ".join(str(v.get("text", "")) for v in (raw.get("jobAd", {}).get("sections") or {}).values()))
            extra = (raw.get("typeOfEmployment") or {}).get("label", "")
            work_model = "remote" if address.get("remote") else ""
        else:
            title = raw.get("title")
            addresses = raw.get("locations") or [raw]
            loc = "; ".join(", ".join(str(a.get(k)) for k in ("city", "country") if a.get(k)) for a in addresses)
            country = next((a.get("country_code") for a in addresses if a.get("country_code")), None)
            url = raw.get("careers_apply_url") or raw.get("careers_url", "")
            source_url = raw.get("careers_url", url)
            date = raw.get("published_at")
            description = plain(str(raw.get("description", "")) + " " + str(raw.get("requirements", "")))
            extra = str(raw.get("employment_type", ""))
            work_model = "remote" if raw.get("remote") else ""
        salary_min = salary_max = None
        job_type = "Part-time" if "part" in extra.lower() else "Contract" if "contract" in extra.lower() else "Full-time"
    elif kind == "jobtech":
        title = raw.get("headline", "")
        employer = raw.get("employer") or {}
        company = employer.get("name") or company
        address = raw.get("workplace_address") or {}
        location = [address.get(k) for k in ("city", "municipality", "region", "country") if address.get(k)]
        loc = ", ".join(dict.fromkeys(location))
        country = address.get("country_code") or "SE"
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
        country = "US"
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
        url, date = raw.get("applyUrl") or raw.get("hostedUrl", ""), raw.get("createdAt")
        source_url = raw.get("hostedUrl", url)
        country = raw.get("country")
        description = plain(" ".join([raw.get("description", ""), raw.get("descriptionPlain", ""), raw.get("additional", "")]))
        cats = raw.get("categories") or {}
        extra = " ".join(str(cats.get(k, "")) for k in ("team", "department", "commitment", "workplaceType"))
        salary = (raw.get("salaryRange") or {})
        currency = salary.get("currency")
        salary_min, salary_max = clean_salary(salary.get("min")), clean_salary(salary.get("max"))
        job_type = "Contract" if "contract" in extra.lower() else "Full-time"
        work_model = str((raw.get("categories") or {}).get("workplaceType", ""))
    elif kind == "ashby":
        title, loc = raw.get("title"), raw.get("location", "")
        url, date = raw.get("applyUrl") or raw.get("jobUrl", ""), raw.get("publishedAt")
        source_url = raw.get("jobUrl", url)
        country = ((raw.get("address") or {}).get("postalAddress") or {}).get("addressCountry")
        description = plain(" ".join([raw.get("descriptionPlain", ""), raw.get("descriptionHtml", "")]))
        employment_type = raw.get("employmentType", [])
        extra = str(employment_type) if isinstance(employment_type, str) else " ".join(str(x) for x in employment_type if x)
        comp = raw.get("compensation") or {}
        currency = comp.get("currencyCode")
        salary_min = clean_salary(comp.get("minValue"))
        salary_max = clean_salary(comp.get("maxValue"))
        job_type = "Contract" if "contract" in extra.lower() else "Full-time"
        work_model = str(raw.get("workplaceType", ""))
    elif kind == "jobicy":
        title = raw.get("jobTitle")
        company = raw.get("companyName") or company
        url = source_url = attributed_url(raw.get("url"), "jobicy.com")
        loc = plain(raw.get("jobGeo")) or "Location not listed"
        country = restriction_country(loc)
        date = raw.get("pubDate")
        description = plain(raw.get("jobDescription", ""))
        extra = str(raw.get("jobType") or "")
        employment = raw.get('jobType')
        job_type = feed_employment(employment[0] if isinstance(employment, list) and employment else employment)
        work_model = "remote"
        currency = raw.get("salaryCurrency") or None
        salary_min = clean_salary(raw.get("salaryMin"))
        salary_max = clean_salary(raw.get("salaryMax"))
        salary_period = raw.get("salaryPeriod") or None
    elif kind == "remoteok":
        if not isinstance(raw.get("id"), (str, int)) or isinstance(raw.get("id"), bool) or not str(raw["id"]).strip():
            raise ValueError("RemoteOK record requires a provider job ID")
        title = raw.get("position")
        company = raw.get("company") or company
        url = source_url = attributed_url(raw.get("url"), "remoteok.com")
        loc = plain(raw.get("location")) or "Location not listed"
        country = restriction_country(loc)
        date = raw.get("date")
        description = plain(raw.get("description", ""))
        extra = " ".join(raw.get("tags", []))
        job_type = feed_employment(raw.get("job_type", ""))
        work_model = "remote"
        salary_min = clean_salary(raw.get("salary_min"))
        salary_max = clean_salary(raw.get("salary_max"))
        currency = None
        salary_period = None
    elif kind == "arbeitnow":
        title = raw.get("title")
        company = raw.get("company_name") or company
        url = source_url = attributed_url(raw.get("url"), "arbeitnow.com")
        loc = plain(raw.get("location")) or "Remote"
        country = restriction_country(loc) if loc != "Remote" else None
        date = raw.get("created_at")
        if isinstance(date, (int, float)):
            date = datetime.fromtimestamp(date, timezone.utc).isoformat()
        description = plain(raw.get("description", ""))
        extra = " ".join(raw.get("tags", [])) + " " + " ".join(raw.get("job_types", []))
        job_type = feed_employment(raw.get("job_types", [""])[0] if raw.get("job_types") else "")
        work_model = "remote" if raw.get("remote") else "on-site"
        salary_min = salary_max = None
        currency = None
        salary_period = None
    title = plain(title)
    loc = plain(loc)
    text = f"{title} {description} {extra}".lower()
    matched = [label for label, terms in AI_TERMS.items() if any(has_term(text, term) for term in terms)]
    signals = [term for term in AI_SIGNAL_TERMS if has_term(text, term)]
    expired = expires_at is not None and datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    is_ai = bool(signals) and not expired and not (kind == "ashby" and raw.get("isListed") is False)
    score = min(99, 66 + len(set(signals)) * 4 + (8 if any(has_term(text, term) for term in ("copilot", "cursor", "claude code", "ai-assisted", "ai-native")) else 0))
    model = f"{work_model} {loc} {text[:500]}".lower()
    work_mode = "Remote" if any(x in model for x in ("remote", "distans", "fully distributed")) else "Hybrid" if any(x in model for x in ("hybrid", "hybridarbete")) else "On-site"
    level_patterns = {"Lead": r"principal|staff|lead", "Senior": r"senior|sr\.?", "Mid": r"mid.?level|intermediate", "Entry": r"junior|entry.?level|graduate"}
    level = next((x for x in ("Lead", "Senior", "Mid", "Entry") if re.search(rf"\b(?:{level_patterns[x]})\b", title.lower())), "Any level")
    identity_board = "public" if kind in ("jobtech", "usajobs", "himalayas", "remotive", "jobicy", "remoteok", "arbeitnow") else board
    provider_id = raw.get("guid") if kind == "himalayas" else raw.get('id') or raw.get('gh_jid') or raw.get('MatchedObjectId') or url
    stable_id = f"{kind}:{identity_board}:{provider_id}"
    tags = []
    for label, terms in AI_TERMS.items():
        if any(has_term(text, term) for term in terms):
            labels = {"copilot": "Copilot", "cursor": "Cursor", "claude code": "Claude Code", "agent": "AI agents", "workflow": "AI workflow", "review": "Code review", "machine learning": "Machine learning", "genai": "Generative AI", "ai platform": "AI infrastructure", "research": "AI research"}
            tags.append(labels[label])
    return {
        "id": stable_id, "title": title, "company": company, "location": loc or "Location not listed",
        "work_mode": work_mode, "level": level, "type": job_type, "salary_min": salary_min,
        "salary_max": salary_max, "posted_at": date_iso(date), "url": url,
        "description": description, "tags": tags, "focus": matched,
        "ai_explicit": is_ai, "match": score, "source": kind, "board": board, "source_url": source_url,
        "currency": currency, "country_code": str(country).upper() if country and re.fullmatch(r"[A-Za-z]{2}", str(country)) else None,
        "expires_at": expires_at, "salary_period": salary_period,
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
