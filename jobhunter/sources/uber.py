from __future__ import annotations

import json
import urllib.request
from datetime import datetime
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import strip_html


class UberPlatform(JobPlatform):
    """Adapter over Uber's public careers search API.

    Uber's site posts queries to a JSON endpoint; unlike the ATS boards this
    one accepts the query directly, so each generated query is sent through.
    """

    name = "company:uber"
    api_url = "https://www.uber.com/api/loadSearchJobsResults?localeCode=en"

    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = timeout

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        body = json.dumps(
            {"params": {"query": query.role or query.text}, "page": 0, "limit": min(limit, 50)}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.api_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (jobhunter)",
                "x-csrf-token": "x",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        results = (((payload or {}).get("data") or {}).get("results")) or []
        return [self._normalize_job(item) for item in results if isinstance(item, dict)][:limit]

    def _normalize_job(self, item: dict[str, Any]) -> JobPosting:
        job_id = str(item.get("id") or "")
        location = _format_location(item.get("location"))
        tags = tuple(str(v) for v in (item.get("department"), item.get("team"), item.get("timeType")) if v)
        return JobPosting(
            source=self.name,
            source_id=job_id,
            title=str(item.get("title") or ""),
            company="Uber",
            url=f"https://www.uber.com/careers/list/{job_id}/" if job_id else "https://www.uber.com/careers/",
            location=location,
            description=strip_html(str(item.get("description") or ""))[:4000],
            tags=tags,
            posted_at=_parse_datetime(item.get("creationDate")),
            raw={"id": job_id, "timeType": item.get("timeType")},
        )


def _format_location(value: Any) -> str | None:
    if not isinstance(value, dict):
        return None
    parts = [value.get("city"), value.get("region"), value.get("countryName") or value.get("country")]
    return ", ".join(str(p) for p in parts if p) or None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
