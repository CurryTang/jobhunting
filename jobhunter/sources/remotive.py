from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform


class RemotivePlatform(JobPlatform):
    """Adapter for Remotive's public remote jobs API."""

    name = "remotive"
    base_url = "https://remotive.com/api/remote-jobs"

    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        params = {"search": query.text, "limit": str(limit)}
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "jobhunter-demo/0.1 (+https://example.local)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [self._normalize_job(job) for job in payload.get("jobs", [])[:limit]]

    def _normalize_job(self, job: dict) -> JobPosting:
        posted_at = None
        raw_date = job.get("publication_date")
        if raw_date:
            try:
                posted_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                posted_at = None
        description = _strip_html(str(job.get("description") or ""))
        tags = tuple(
            item
            for item in (
                job.get("category"),
                job.get("job_type"),
                job.get("candidate_required_location"),
            )
            if item
        )
        return JobPosting(
            source=self.name,
            source_id=str(job.get("id", "")),
            title=str(job.get("title") or ""),
            company=str(job.get("company_name") or ""),
            url=str(job.get("url") or ""),
            location=job.get("candidate_required_location"),
            description=description,
            tags=tags,
            salary=job.get("salary"),
            posted_at=posted_at,
            raw=job,
        )


def _strip_html(value: str) -> str:
    value = re.sub(r"<(script|style).*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"&nbsp;?", " ", value)
    return re.sub(r"\s+", " ", value).strip()
