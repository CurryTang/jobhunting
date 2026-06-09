from __future__ import annotations

import json
import re
import urllib.request
from html import unescape
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import filter_and_rank


class YCJobsPlatform(JobPlatform):
    """Adapter for public YC startup jobs embedded on ycombinator.com/jobs."""

    name = "yc"
    jobs_url = "https://www.ycombinator.com/jobs"

    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self._jobs_cache: list[JobPosting] | None = None

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        # The embedded payload is one global board that ignores queries, so
        # fetch it once per run and filter locally per query. Filtering keeps
        # different queries from returning the same arbitrary head slice.
        jobs = self._fetch_all_jobs()
        matched = filter_and_rank(jobs, query, limit=limit)
        return matched or jobs[:limit]

    def _fetch_all_jobs(self) -> list[JobPosting]:
        if self._jobs_cache is not None:
            return self._jobs_cache
        request = urllib.request.Request(
            self.jobs_url,
            headers={"User-Agent": "jobhunter-demo/0.1 (+https://example.local)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            html = response.read().decode("utf-8", errors="replace")
        self._jobs_cache = [self._normalize_job(job) for job in _extract_job_postings(html)]
        return self._jobs_cache

    def _normalize_job(self, job: dict[str, Any]) -> JobPosting:
        tags = tuple(
            str(value)
            for value in (
                job.get("type"),
                job.get("prettyRole"),
                job.get("roleSpecificType"),
                *(job.get("skills") or []),
            )
            if value
        )
        description = " ".join(
            str(part)
            for part in (
                job.get("companyOneLiner"),
                job.get("prettyRole"),
                job.get("roleSpecificType"),
                " ".join(job.get("skills") or []),
            )
            if part
        )
        url = job.get("url") or ""
        if url.startswith("/"):
            url = "https://www.ycombinator.com" + url
        return JobPosting(
            source=self.name,
            source_id=str(job.get("id") or url),
            title=str(job.get("title") or ""),
            company=str(job.get("companyName") or ""),
            url=url or str(job.get("applyUrl") or ""),
            location=job.get("location"),
            description=description,
            tags=tags,
            salary=job.get("salaryRange"),
            raw=job,
        )


def _extract_job_postings(html: str) -> list[dict[str, Any]]:
    match = re.search(r'data-page="([^"]+)"', html)
    if not match:
        return []
    data = json.loads(unescape(match.group(1)))
    postings = data.get("props", {}).get("jobPostings", [])
    return [posting for posting in postings if isinstance(posting, dict)]
