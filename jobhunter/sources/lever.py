from __future__ import annotations

import os
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import fetch_json, filter_and_rank, strip_html

# Override with JOBHUNTER_LEVER_COMPANIES="slug1,slug2" (comma-separated).
DEFAULT_COMPANIES: tuple[str, ...] = (
    "mistral",
    "palantir",
    "plaid",
    "voleon",
)

_COMPANY_DISPLAY_NAMES = {
    "mistral": "Mistral AI",
    "voleon": "The Voleon Group",
}


class LeverPlatform(JobPlatform):
    """Adapter over the public Lever postings API.

    One request per configured company per run; companies that 404 are
    skipped silently.
    """

    name = "lever"
    api_template = "https://api.lever.co/v0/postings/{company}?mode=json"

    def __init__(self, *, companies: tuple[str, ...] | None = None, timeout: float = 20.0) -> None:
        self.timeout = timeout
        env_companies = os.environ.get("JOBHUNTER_LEVER_COMPANIES", "")
        self.companies = companies or tuple(part.strip() for part in env_companies.split(",") if part.strip()) or DEFAULT_COMPANIES
        self._jobs_cache: list[JobPosting] | None = None

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        return filter_and_rank(self._fetch_all_jobs(), query, limit=limit)

    def _fetch_all_jobs(self) -> list[JobPosting]:
        if self._jobs_cache is not None:
            return self._jobs_cache
        jobs: list[JobPosting] = []
        for company in self.companies:
            url = self.api_template.format(company=urllib.parse.quote(company))
            try:
                payload = fetch_json(url, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                raise
            display = _COMPANY_DISPLAY_NAMES.get(company, company.replace("-", " ").title())
            for item in payload if isinstance(payload, list) else []:
                if isinstance(item, dict):
                    jobs.append(self._normalize_job(item, company=display))
        self._jobs_cache = jobs
        return self._jobs_cache

    def _normalize_job(self, item: dict[str, Any], *, company: str) -> JobPosting:
        categories = item.get("categories") or {}
        location = categories.get("location") or None
        workplace = item.get("workplaceType")
        if workplace and location and str(workplace).lower() == "remote" and "remote" not in str(location).lower():
            location = f"Remote - {location}"
        tags = tuple(
            str(value)
            for value in (categories.get("team"), categories.get("commitment"), workplace)
            if value
        )
        posted_at = None
        created = item.get("createdAt")
        if isinstance(created, (int, float)) and created > 0:
            posted_at = datetime.fromtimestamp(created / 1000, tz=timezone.utc)
        # Responsibilities/requirements usually live in `lists`, not
        # descriptionPlain — without them relevance filtering misses roles
        # whose ML/Python evidence only appears there.
        description_parts = [str(item.get("descriptionPlain") or "")]
        for entry in item.get("lists") or []:
            if isinstance(entry, dict):
                description_parts.append(str(entry.get("text") or ""))
                description_parts.append(strip_html(str(entry.get("content") or "")))
        description_parts.append(str(item.get("additionalPlain") or ""))
        return JobPosting(
            source=self.name,
            source_id=str(item.get("id") or ""),
            title=str(item.get("text") or ""),
            company=company,
            url=str(item.get("hostedUrl") or item.get("applyUrl") or ""),
            location=str(location) if location else None,
            description=" ".join(part for part in description_parts if part)[:4000],
            tags=tags,
            posted_at=posted_at,
            raw={key: value for key, value in item.items() if key not in {"description", "descriptionPlain", "lists"}},
        )
