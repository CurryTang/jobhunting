from __future__ import annotations

import urllib.error
import urllib.parse
from datetime import datetime
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import fetch_json, filter_and_rank, strip_html


class AshbyPlatform(JobPlatform):
    """Adapter over the public Ashby job-board posting API.

    One request per configured organisation per run; boards that 404 (wrong
    slug or not on Ashby) are skipped silently.
    """

    name = "ashby"
    api_template = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

    def __init__(self, *, slugs: tuple[str, ...], timeout: float = 20.0) -> None:
        self.timeout = timeout
        self.slugs = slugs
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
        for slug in self.slugs:
            url = self.api_template.format(slug=urllib.parse.quote(slug))
            try:
                payload = fetch_json(url, timeout=self.timeout, headers={"User-Agent": "Mozilla/5.0 (jobhunter)"})
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                raise
            for item in payload.get("jobs", []) if isinstance(payload, dict) else []:
                if isinstance(item, dict) and item.get("isListed", True):
                    jobs.append(self._normalize_job(item, slug=slug))
        self._jobs_cache = jobs
        return self._jobs_cache

    def _normalize_job(self, item: dict[str, Any], *, slug: str) -> JobPosting:
        location = item.get("location") or None
        if item.get("isRemote") and location and "remote" not in str(location).lower():
            location = f"Remote - {location}"
        tags = tuple(
            str(value)
            for value in (item.get("department"), item.get("team"), item.get("employmentType"))
            if value
        )
        return JobPosting(
            source=f"company:{slug}",
            source_id=str(item.get("id") or ""),
            title=str(item.get("title") or ""),
            company=_display_name(slug),
            url=str(item.get("jobUrl") or item.get("applyUrl") or ""),
            location=str(location) if location else None,
            description=strip_html(str(item.get("descriptionPlain") or item.get("descriptionHtml") or ""))[:4000],
            tags=tags,
            posted_at=_parse_datetime(item.get("publishedAt")),
            raw={
                "applyUrl": item.get("applyUrl"),
                "jobUrl": item.get("jobUrl"),
                "employmentType": item.get("employmentType"),
            },
        )


def _display_name(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
