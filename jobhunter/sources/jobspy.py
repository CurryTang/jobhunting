from __future__ import annotations

import os
import re
import time
from datetime import datetime
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import filter_and_rank


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


class JobSpyPlatform(JobPlatform):
    """Adapter for python-jobspy-backed job boards.

    LinkedIn rate-limits rapid repeated calls hard, so this adapter does NOT
    scrape once per generated query. Instead it scrapes each distinct search
    term at most once per run (with a small retry on an empty result), pools
    the postings, and filters that pool locally for every query. That turns
    ~10 throttled scrapes into a handful of productive ones.
    """

    def __init__(
        self,
        *,
        site_name: str = "linkedin",
        results_wanted: int = 50,
        hours_old: int | None = 336,
        fetch_linkedin_description: bool = False,
        max_calls: int = 6,
        retry_on_empty: bool = True,
        retry_delay: float = 3.0,
        proxies: list[str] | None = None,
    ) -> None:
        self.site_name = site_name
        self.name = f"jobspy:{site_name}"
        self.results_wanted = results_wanted
        self.hours_old = hours_old
        self.fetch_linkedin_description = fetch_linkedin_description
        self.max_calls = max_calls
        self.retry_on_empty = retry_on_empty
        self.retry_delay = retry_delay
        # LinkedIn rate-limits by IP. Proxies (JOBHUNTER_LINKEDIN_PROXIES, a
        # comma list of host:port or user:pass@host:port) are the reliable fix.
        self.proxies = proxies if proxies is not None else _proxies_from_env()
        self._pool: list[JobPosting] = []
        self._pool_keys: set[str] = set()
        self._scraped: set[str] = set()
        self._calls = 0

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        location = _choose_location(query, profile)
        term = _jobspy_query_text(query)
        cache_key = f"{_norm(term)}|{_norm(location or '')}"
        if cache_key not in self._scraped and self._calls < self.max_calls:
            self._scraped.add(cache_key)
            self._calls += 1
            for posting in self._scrape(term, location, query):
                key = posting.source_id or posting.url
                if key and key not in self._pool_keys:
                    self._pool_keys.add(key)
                    self._pool.append(posting)
        return filter_and_rank(self._pool, query, limit=limit)

    def _scrape(self, term: str, location: str | None, query: SearchQuery) -> list[JobPosting]:
        scrape_jobs = _load_scrape_jobs()
        kwargs: dict[str, Any] = {
            "site_name": [self.site_name],
            "search_term": term,
            "location": location,
            "results_wanted": self.results_wanted,
            "verbose": 0,
        }
        if query.remote is not None:
            kwargs["is_remote"] = query.remote
        if self.hours_old is not None:
            kwargs["hours_old"] = self.hours_old
        if self.site_name == "linkedin":
            kwargs["linkedin_fetch_description"] = self.fetch_linkedin_description
        if self.proxies:
            kwargs["proxies"] = self.proxies

        records = self._call_with_retry(scrape_jobs, kwargs)
        return [self._normalize_record(record) for record in records]

    def _call_with_retry(self, scrape_jobs, kwargs: dict[str, Any]) -> list[dict[str, Any]]:
        try:
            records = _records_from_jobspy_result(scrape_jobs(**kwargs))
        except Exception:  # noqa: BLE001 - transient scraper/network failure.
            records = []
        if records or not self.retry_on_empty:
            return records
        # An empty LinkedIn result is usually a soft rate-limit; back off once.
        time.sleep(self.retry_delay)
        try:
            return _records_from_jobspy_result(scrape_jobs(**kwargs))
        except Exception:  # noqa: BLE001
            return []

    def _normalize_record(self, record: dict[str, Any]) -> JobPosting:
        source_id = str(record.get("id") or record.get("job_id") or record.get("job_url") or "")
        location = _format_location(record.get("location") or record)
        salary = _format_salary(record)
        return JobPosting(
            source=self.name,
            source_id=source_id,
            title=str(record.get("title") or ""),
            company=str(record.get("company") or ""),
            url=str(record.get("job_url") or record.get("job_url_direct") or ""),
            location=location,
            description=str(record.get("description") or ""),
            tags=tuple(str(value) for value in (record.get("job_type"), record.get("job_level")) if value),
            salary=salary,
            posted_at=_parse_datetime(record.get("date_posted")),
            raw=record,
        )


class LinkedInJobSpyPlatform(JobSpyPlatform):
    """JobSpy adapter configured for LinkedIn job search."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(site_name="linkedin", **kwargs)


class IndeedJobSpyPlatform(JobSpyPlatform):
    """JobSpy adapter for Indeed — a broad aggregator that is far less
    aggressively rate-limited than LinkedIn, so it makes a reliable stand-in
    when LinkedIn throttles."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(site_name="indeed", **kwargs)


class GlassdoorJobSpyPlatform(JobSpyPlatform):
    """JobSpy adapter for Glassdoor."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(site_name="glassdoor", **kwargs)


def _load_scrape_jobs():
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError(
            "LinkedIn search uses the optional python-jobspy package. "
            "Install it with `pip install -U python-jobspy` and run with Python >=3.10."
        ) from exc
    return scrape_jobs


def _proxies_from_env() -> list[str] | None:
    raw = os.environ.get("JOBHUNTER_LINKEDIN_PROXIES", "").strip()
    if not raw:
        return None
    proxies = [part.strip() for part in raw.split(",") if part.strip()]
    return proxies or None


def _jobspy_query_text(query: SearchQuery) -> str:
    if query.role and query.skills:
        return " ".join((query.role, *query.skills[:2]))
    return query.text


def _choose_location(query: SearchQuery, profile: UserProfile) -> str | None:
    if query.location:
        return _display_location(query.location)
    if "united states" in profile.locations:
        return "United States"
    return _display_location(profile.locations[0]) if profile.locations else None


def _display_location(location: str) -> str:
    aliases = {
        "usa": "United States",
        "united states": "United States",
        "east lansing": "East Lansing, MI",
        "michigan": "Michigan",
        "remote": "United States",
    }
    return aliases.get(location.lower(), location.title())


def _records_from_jobspy_result(jobs: Any) -> list[dict[str, Any]]:
    if hasattr(jobs, "to_dict"):
        records = jobs.to_dict("records")
        return [_clean_record(dict(record)) for record in records]
    if isinstance(jobs, list):
        return [_clean_record(dict(record)) for record in jobs if isinstance(record, dict)]
    return []


def _clean_record(record: dict[str, Any]) -> dict[str, Any]:
    # Pandas rows surface missing values as NaN floats; treat them as absent
    # so titles/companies/salaries never render as "nan".
    return {key: (None if isinstance(value, float) and value != value else value) for key, value in record.items()}


def _format_location(value: Any) -> str | None:
    if isinstance(value, dict):
        parts = [value.get("city"), value.get("state"), value.get("country")]
        return ", ".join(str(part) for part in parts if part) or None
    if isinstance(value, str) and value:
        return value
    city = getattr(value, "city", None)
    state = getattr(value, "state", None)
    country = getattr(value, "country", None)
    parts = [city, state, country]
    return ", ".join(str(part) for part in parts if part) or None


def _format_salary(record: dict[str, Any]) -> str | None:
    min_amount = record.get("min_amount")
    max_amount = record.get("max_amount")
    interval = record.get("interval")
    currency = record.get("currency") or ""
    if min_amount and max_amount:
        return f"{currency}{min_amount}-{currency}{max_amount} {interval or ''}".strip()
    if min_amount:
        return f"{currency}{min_amount}+ {interval or ''}".strip()
    if max_amount:
        return f"up to {currency}{max_amount} {interval or ''}".strip()
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None
