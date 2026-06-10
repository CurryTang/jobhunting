from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import os

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import fetch_json, filter_and_rank, strip_html

# Curated registry of companies with a verified public career API, mapping a
# friendly name to its provider. Providers: amazon/google/uber (built-in),
# greenhouse:/lever:/ashby:<slug> (delegated). Users type the friendly name
# (e.g. "openai", "stripe") and never need to know which ATS a company uses.
COMPANY_REGISTRY: dict[str, str] = {
    "abnormalsecurity": "greenhouse:abnormalsecurity",
    "abridge": "ashby:abridge",
    "affirm": "greenhouse:affirm",
    "airbnb": "greenhouse:airbnb",
    "airtable": "greenhouse:airtable",
    "akunacapital": "greenhouse:akunacapital",
    "amazon": "amazon",
    "angellist": "lever:angellist",
    "anthropic": "greenhouse:anthropic",
    "anyscale": "ashby:anyscale",
    "asana": "greenhouse:asana",
    "baseten": "ashby:baseten",
    "betterment": "greenhouse:betterment",
    "brex": "greenhouse:brex",
    "browserbase": "ashby:browserbase",
    "calendly": "greenhouse:calendly",
    "carta": "greenhouse:carta",
    "celonis": "greenhouse:celonis",
    "checkr": "greenhouse:checkr",
    "chime": "greenhouse:chime",
    "clickhouse": "greenhouse:clickhouse",
    "cloudflare": "greenhouse:cloudflare",
    "cockroachlabs": "greenhouse:cockroachlabs",
    "cohere": "ashby:cohere",
    "coinbase": "greenhouse:coinbase",
    "consensys": "greenhouse:consensys",
    "coupang": "greenhouse:coupang",
    "crusoe": "ashby:crusoe",
    "cursor": "ashby:cursor",
    "databricks": "greenhouse:databricks",
    "datadog": "greenhouse:datadog",
    "decagon": "ashby:decagon",
    "discord": "greenhouse:discord",
    "dropbox": "greenhouse:dropbox",
    "elastic": "greenhouse:elastic",
    "elevenlabs": "ashby:elevenlabs",
    "faire": "greenhouse:faire",
    "figma": "greenhouse:figma",
    "fivetran": "greenhouse:fivetran",
    "flowtraders": "greenhouse:flowtraders",
    "flexport": "greenhouse:flexport",
    "gemini": "greenhouse:gemini",
    "gitlab": "greenhouse:gitlab",
    "gocardless": "greenhouse:gocardless",
    "google": "google",
    "gusto": "greenhouse:gusto",
    "harvey": "ashby:harvey",
    "hedra": "ashby:hedra",
    "imc": "greenhouse:imc",
    "instacart": "greenhouse:instacart",
    "janestreet": "greenhouse:janestreet",
    "jumptrading": "greenhouse:jumptrading",
    "lambda": "ashby:lambda",
    "langchain": "ashby:langchain",
    "linear": "ashby:linear",
    "llamaindex": "ashby:llamaindex",
    "lyft": "greenhouse:lyft",
    "marqeta": "greenhouse:marqeta",
    "mercor": "ashby:mercor",
    "mercury": "greenhouse:mercury",
    "mistral": "lever:mistral",
    "modal": "ashby:modal",
    "mongodb": "greenhouse:mongodb",
    "netflix": "lever:netflix",
    "netlify": "greenhouse:netlify",
    "notion": "ashby:notion",
    "nubank": "greenhouse:nubank",
    "nuro": "greenhouse:nuro",
    "okta": "greenhouse:okta",
    "oldmissioncapital": "greenhouse:oldmissioncapital",
    "openai": "ashby:openai",
    "palantir": "lever:palantir",
    "pathai": "greenhouse:pathai",
    "perplexity": "ashby:perplexity",
    "pika": "ashby:pika",
    "pinterest": "greenhouse:pinterest",
    "plaid": "lever:plaid",
    "planetscale": "greenhouse:planetscale",
    "point72": "greenhouse:point72",
    "postman": "greenhouse:postman",
    "ramp": "ashby:ramp",
    "reddit": "greenhouse:reddit",
    "robinhood": "greenhouse:robinhood",
    "roblox": "greenhouse:roblox",
    "rubrik": "greenhouse:rubrik",
    "samsara": "greenhouse:samsara",
    "scaleai": "greenhouse:scaleai",
    "shieldai": "lever:shieldai",
    "sierra": "ashby:sierra",
    "snowflake": "ashby:snowflake",
    "sofi": "greenhouse:sofi",
    "spacex": "greenhouse:spacex",
    "squarespace": "greenhouse:squarespace",
    "starburst": "greenhouse:starburst",
    "stockx": "greenhouse:stockx",
    "stripe": "greenhouse:stripe",
    "suno": "ashby:suno",
    "thinking-machines-lab": "ashby:thinking-machines-lab",
    "togetherai": "greenhouse:togetherai",
    "twitch": "greenhouse:twitch",
    "uber": "uber",
    "vercel": "greenhouse:vercel",
    "verkada": "greenhouse:verkada",
    "voleon": "lever:voleon",
    "waymo": "greenhouse:waymo",
    "weaviate": "ashby:weaviate",
    "webflow": "greenhouse:webflow",
    "writer": "ashby:writer",
    "xai": "greenhouse:xai",
}

# Friendly aliases for companies whose canonical key is awkward to type.
COMPANY_ALIASES: dict[str, str] = {
    "thinkingmachines": "thinking-machines-lab",
    "thinking-machines": "thinking-machines-lab",
    "tml": "thinking-machines-lab",
    "scale": "scaleai",
    "together": "togetherai",
    "cockroach": "cockroachlabs",
    "jane-street": "janestreet",
    "jane_street": "janestreet",
    "jump-trading": "jumptrading",
    "jump": "jumptrading",
    "imc-trading": "imc",
    "imctrading": "imc",
    "akuna": "akunacapital",
    "old-mission": "oldmissioncapital",
}

# All registered companies are searched by default — a deep sweep across every
# verified board. Override with JOBHUNTER_COMPANIES or .jobhunter/companies.json
# to narrow it (e.g. JOBHUNTER_COMPANIES="openai,anthropic,databricks").
DEFAULT_COMPANIES: tuple[str, ...] = tuple(sorted(COMPANY_REGISTRY))

# Companies whose careers site has no usable public JSON endpoint. They warn
# once and are skipped so a configured list never breaks the run.
UNSUPPORTED_NOTES = {
    "meta": "Meta careers is GraphQL-rendered with no public JSON endpoint; entry skipped.",
    "microsoft": "Microsoft careers API rejects unauthenticated requests; entry skipped.",
    "tiktok": "TikTok careers sits behind a redirecting gateway with no stable public JSON endpoint; entry skipped.",
    "bytedance": "ByteDance careers has no public JSON endpoint reachable without a session; entry skipped.",
    "salesforce": "Salesforce uses Workday, which has no simple public JSON search; entry skipped.",
    "paypal": "PayPal uses Workday, which has no simple public JSON search; entry skipped.",
    "linkedin": "Use --sources linkedin (JobSpy) for LinkedIn; it is not a direct company board.",
    "bloomberg": "Bloomberg careers has no public JSON board endpoint; entry skipped.",
    "twosigma": "Two Sigma uses a custom/Workday careers site with no public JSON board; entry skipped.",
    "two-sigma": "Two Sigma uses a custom/Workday careers site with no public JSON board; entry skipped.",
    "citadel": "Citadel uses a custom careers site with no public JSON board; entry skipped.",
    "citadelsecurities": "Citadel Securities uses a custom careers site with no public JSON board; entry skipped.",
    "optiver": "Optiver's public board returns no jobs through the Greenhouse API; entry skipped.",
}


class CompanyBoardsPlatform(JobPlatform):
    """Search configured company career sites directly.

    Defaults to a deep sweep across every company in COMPANY_REGISTRY (100+
    verified boards). Built-in providers: `amazon` (amazon.jobs JSON search),
    `google` (careers.google.com payload), `uber` (uber.com careers API), plus
    `greenhouse:`/`lever:`/`ashby:<slug>` delegates. Entries can be friendly
    registry names ("openai") or raw provider specs. Unsupported or unreachable
    companies warn once and are skipped.
    """

    name = "companies"

    def __init__(self, *, companies: tuple[str, ...] | None = None, timeout: float = 15.0) -> None:
        self.timeout = timeout
        self.companies = tuple(companies) if companies else _configured_companies()
        self.company_errors: list[str] = []
        self._delegates: dict[str, JobPlatform] = {}
        # Each supported entry is a resolved provider spec: "amazon"/"google"/
        # "uber" or "<provider>:<slug>".
        self._supported: list[str] = []
        for entry in self.companies:
            spec = _resolve_company(entry)
            if spec is None:
                normalized = entry.strip().lower()
                if normalized in UNSUPPORTED_NOTES:
                    warnings.warn(f"companies source: {UNSUPPORTED_NOTES[normalized]}", stacklevel=2)
                continue
            self._supported.append(spec)

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        self.company_errors = []
        per_company: list[list[JobPosting]] = []
        for entry in self._supported:
            try:
                jobs = self._search_company(entry, query, profile, limit=limit)
            except Exception as exc:  # noqa: BLE001 - one company must not sink the rest.
                self.company_errors.append(f"{entry}: {exc}")
                continue
            ranked = filter_and_rank(jobs, query, limit=limit)
            if ranked:
                per_company.append(ranked)
        # Round-robin across companies: a keyword-stuffed board (e.g. Amazon)
        # must not crowd every other configured company out of the cap.
        merged: list[JobPosting] = []
        index = 0
        while len(merged) < limit and any(index < len(jobs) for jobs in per_company):
            for jobs in per_company:
                if index < len(jobs) and len(merged) < limit:
                    merged.append(jobs[index])
            index += 1
        return merged

    def _search_company(self, entry: str, query: SearchQuery, profile: UserProfile, *, limit: int) -> list[JobPosting]:
        if entry == "amazon":
            return self._search_amazon(query, limit=limit)
        if entry == "google":
            return self._search_google(query, limit=limit)
        if entry == "uber":
            from jobhunter.sources.uber import UberPlatform

            return self._delegates.setdefault("uber", UberPlatform(timeout=self.timeout)).search(query, profile, limit=limit)
        if ":" in entry:
            provider, _, slug = entry.partition(":")
            delegate = self._delegate_for(provider.strip(), slug.strip())
            if delegate is not None:
                return delegate.search(query, profile, limit=limit)
        raise ValueError(
            f"unknown company entry '{entry}'. Use a registered name, amazon, google, uber, "
            "greenhouse:<slug>, lever:<slug>, or ashby:<slug>."
        )

    def _delegate_for(self, provider: str, slug: str) -> JobPlatform | None:
        key = f"{provider}:{slug}"
        if key in self._delegates:
            return self._delegates[key]
        if provider == "greenhouse":
            from jobhunter.sources.greenhouse import GreenhousePlatform

            delegate: JobPlatform = GreenhousePlatform(boards=(slug,), timeout=self.timeout)
        elif provider == "lever":
            from jobhunter.sources.lever import LeverPlatform

            delegate = LeverPlatform(companies=(slug,), timeout=self.timeout)
        elif provider == "ashby":
            from jobhunter.sources.ashby import AshbyPlatform

            delegate = AshbyPlatform(slugs=(slug,), timeout=self.timeout)
        else:
            return None
        self._delegates[key] = delegate
        return delegate

    def _search_amazon(self, query: SearchQuery, *, limit: int) -> list[JobPosting]:
        params = urllib.parse.urlencode({"base_query": _provider_query(query), "result_limit": min(limit, 50), "offset": 0})
        payload = fetch_json(
            f"https://www.amazon.jobs/en/search.json?{params}",
            timeout=self.timeout,
            headers={"User-Agent": "Mozilla/5.0 (jobhunter)"},
        )
        jobs = []
        for item in payload.get("jobs", []) if isinstance(payload, dict) else []:
            if isinstance(item, dict):
                jobs.append(_normalize_amazon_job(item))
        return jobs

    def _search_google(self, query: SearchQuery, *, limit: int) -> list[JobPosting]:
        params = urllib.parse.urlencode({"q": _provider_query(query)})
        url = f"https://www.google.com/about/careers/applications/jobs/results/?{params}"
        request_headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
        request = urllib.request.Request(url, headers=request_headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
        return _parse_google_jobs(html)[:limit]


def _resolve_company(entry: str) -> str | None:
    """Resolve a configured entry to a provider spec, or None to skip it.

    Accepts a registered friendly name ("openai"), an alias ("thinkingmachines"),
    or a raw provider spec ("greenhouse:somenewco" / "ashby:somenewco").
    """

    normalized = entry.strip().lower()
    if not normalized or normalized in UNSUPPORTED_NOTES:
        return None
    if ":" in normalized:
        provider = normalized.split(":", 1)[0]
        return normalized if provider in {"greenhouse", "lever", "ashby"} else None
    normalized = COMPANY_ALIASES.get(normalized, normalized)
    return COMPANY_REGISTRY.get(normalized)


def _provider_query(query: SearchQuery) -> str:
    # Company search engines use AND semantics, so a long skill-stuffed query
    # returns nothing. Search the role family broadly and let filter_and_rank
    # narrow the results locally.
    return query.role or query.text


def _configured_companies() -> tuple[str, ...]:
    env_value = os.environ.get("JOBHUNTER_COMPANIES", "")
    if env_value.strip():
        return tuple(part.strip() for part in env_value.split(",") if part.strip())
    config_path = Path(os.environ.get("JOBHUNTER_COMPANIES_FILE", ".jobhunter/companies.json")).expanduser()
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = None
        if isinstance(data, list):
            entries = tuple(str(item).strip() for item in data if str(item).strip())
            if entries:
                return entries
    return DEFAULT_COMPANIES


def _normalize_amazon_job(item: dict[str, Any]) -> JobPosting:
    posted_at = None
    raw_date = item.get("posted_date")
    if raw_date:
        try:
            posted_at = datetime.strptime(str(raw_date), "%B %d, %Y").replace(tzinfo=timezone.utc)
        except ValueError:
            posted_at = None
    path = str(item.get("job_path") or "")
    description = " ".join(
        strip_html(str(part))
        for part in (item.get("description"), item.get("basic_qualifications"), item.get("preferred_qualifications"))
        if part
    )
    tags = tuple(str(value) for value in (item.get("job_category"), item.get("business_category"), item.get("job_schedule_type")) if value)
    return JobPosting(
        source="company:amazon",
        source_id=str(item.get("id") or item.get("id_icims") or ""),
        title=str(item.get("title") or ""),
        company=str(item.get("company_name") or "Amazon"),
        url=f"https://www.amazon.jobs{path}" if path.startswith("/") else path,
        location=str(item.get("normalized_location") or item.get("location") or "") or None,
        description=description[:4000],
        tags=tags,
        posted_at=posted_at,
        raw={key: item.get(key) for key in ("id", "id_icims", "job_path", "url_next_step", "posted_date", "job_category", "city", "state", "country_code")},
    )


def _parse_google_jobs(html: str) -> list[JobPosting]:
    match = re.search(r"AF_initDataCallback\(\{key: 'ds:1'.*?data:(\[.*?\]), sideChannel", html, re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(1))
    except ValueError:
        return []
    entries = data[0] if isinstance(data, list) and data and isinstance(data[0], list) else []
    jobs: list[JobPosting] = []
    for entry in entries:
        if not isinstance(entry, list) or len(entry) < 11 or not entry[0] or not entry[1]:
            continue
        job_id = str(entry[0])
        title = str(entry[1])
        apply_url = str(entry[2] or "")
        company = str(entry[7] or "Google")
        location = None
        if isinstance(entry[9], list) and entry[9] and isinstance(entry[9][0], list) and entry[9][0]:
            location = str(entry[9][0][0])
        description = " ".join(
            strip_html(str(part[1]))
            for part in (entry[3], entry[4], entry[10])
            if isinstance(part, list) and len(part) > 1 and part[1]
        )
        posted_at = None
        if isinstance(entry[12], list) and entry[12] and isinstance(entry[12][0], (int, float)):
            posted_at = datetime.fromtimestamp(entry[12][0], tz=timezone.utc)
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        jobs.append(
            JobPosting(
                source="company:google",
                source_id=job_id,
                title=title,
                company=company,
                url=f"https://www.google.com/about/careers/applications/jobs/results/{job_id}-{slug}",
                location=location,
                description=description[:4000],
                posted_at=posted_at,
                raw={"id": job_id, "apply_url": apply_url, "company": company},
            )
        )
    return jobs
