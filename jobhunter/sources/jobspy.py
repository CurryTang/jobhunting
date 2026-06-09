from __future__ import annotations

from datetime import datetime
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform


class JobSpyPlatform(JobPlatform):
    """Adapter for python-jobspy-backed job boards."""

    def __init__(
        self,
        *,
        site_name: str = "linkedin",
        results_wanted: int = 20,
        hours_old: int | None = 168,
        fetch_linkedin_description: bool = False,
    ) -> None:
        self.site_name = site_name
        self.name = f"jobspy:{site_name}"
        self.results_wanted = results_wanted
        self.hours_old = hours_old
        self.fetch_linkedin_description = fetch_linkedin_description

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        scrape_jobs = _load_scrape_jobs()
        location = _choose_location(query, profile)
        kwargs: dict[str, Any] = {
            "site_name": [self.site_name],
            "search_term": _jobspy_query_text(query),
            "location": location,
            "results_wanted": min(limit, self.results_wanted),
            "verbose": 0,
        }
        if query.remote is not None:
            kwargs["is_remote"] = query.remote
        if self.hours_old is not None:
            kwargs["hours_old"] = self.hours_old
        if self.site_name == "linkedin":
            kwargs["linkedin_fetch_description"] = self.fetch_linkedin_description

        jobs = scrape_jobs(**kwargs)
        records = _records_from_jobspy_result(jobs)
        return [self._normalize_record(record) for record in records[:limit]]

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


def _load_scrape_jobs():
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError(
            "LinkedIn search uses the optional python-jobspy package. "
            "Install it with `pip install -U python-jobspy` and run with Python >=3.10."
        ) from exc
    return scrape_jobs


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
