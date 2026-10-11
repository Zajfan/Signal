"""Validation for the local employer marketplace, independent of HTTP transport."""
import re
from urllib.parse import urlsplit

AI_TERMS = re.compile(r"\b(ai|artificial intelligence|machine learning|llm|copilot|cursor|claude code|generative ai|ai-assisted|ai-native|ai agent)\b", re.I)
JOB_FIELDS = (
    "title", "company_name", "description", "apply_url", "location", "country_code",
    "work_mode", "employment_type", "salary_min", "salary_max", "salary_currency",
)
EMPLOYMENT_TYPES = ("full-time", "part-time", "contract", "temporary", "internship", "freelance")


def validate_unicode(value):
    """Reject lone surrogate code points before JSON values reach SQLite or UTF-8 output."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ValueError("Request body contains invalid Unicode") from exc
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def required_text(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a nonempty string")
    validate_unicode(value)
    value = value.strip()
    maximum = {"title": 180, "company_name": 180, "location": 180, "description": 12000}.get(key)
    if maximum is not None and len(value) > maximum:
        raise ValueError(f"{key} must contain at most {maximum} characters")
    return value


def absolute_url(value, https_only=False):
    if not isinstance(value, str) or any(c.isspace() for c in value):
        raise ValueError("URL must be an absolute HTTP(S) URL with a hostname")
    try:
        parsed = urlsplit(value)
        valid = parsed.scheme in (("https",) if https_only else ("https", "http")) and parsed.hostname and parsed.port != 0
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("URL must be an absolute HTTP(S) URL with a hostname")
    return value


def validate_job(data):
    if not isinstance(data, dict):
        raise ValueError("Request body must be a JSON object")
    result = {key: required_text(data, key) for key in ("title", "company_name", "description", "apply_url", "location", "country_code")}
    if len(result["description"]) < 40:
        raise ValueError("Description must contain at least 40 characters")
    if not AI_TERMS.search(result["title"] + " " + result["description"]):
        raise ValueError("The role must include an AI or AI-assisted development signal")
    result["apply_url"] = absolute_url(result["apply_url"])
    if not re.fullmatch(r"[A-Za-z]{2}", result["country_code"]):
        raise ValueError("country_code must be a two-letter country code")
    result["country_code"] = result["country_code"].upper()
    mode = data.get("work_mode", "on-site")
    if mode not in ("remote", "hybrid", "on-site"):
        raise ValueError("Invalid work mode")
    result["work_mode"] = mode
    employment = data.get("employment_type", "full-time")
    if employment not in EMPLOYMENT_TYPES:
        raise ValueError("Invalid employment type")
    result["employment_type"] = employment
    for key in ("salary_min", "salary_max"):
        value = data.get(key)
        if value is not None and (type(value) is not int or value < 0 or value > 9223372036854775807):
            raise ValueError(f"{key} must be a nonnegative integer or null")
        result[key] = value
    if result["salary_min"] is not None and result["salary_max"] is not None and result["salary_min"] > result["salary_max"]:
        raise ValueError("salary_min must not exceed salary_max")
    currency = data.get("salary_currency")
    has_salary = result["salary_min"] is not None or result["salary_max"] is not None
    if currency is not None and currency != "":
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Za-z]{3}", currency):
            raise ValueError("salary_currency must be a three-letter currency code")
        currency = currency.upper()
    elif has_salary:
        raise ValueError("salary_currency is required when salary is supplied")
    else:
        currency = None
    result["salary_currency"] = currency
    return result
