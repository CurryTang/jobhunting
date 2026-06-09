from __future__ import annotations

from datetime import datetime
from html import unescape
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import fetch_json, filter_and_rank, strip_html


class RemoteOKPlatform(JobPlatform):
    """Adapter for the RemoteOK public JSON API.

    The API returns the full current board (no query support), so the board
    is fetched once per run and filtered locally per generated query.
    """

    name = "remoteok"
    api_url = "https://remoteok.com/api"

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
        return filter_and_rank(self._fetch_all_jobs(), query, limit=limit)

    def _fetch_all_jobs(self) -> list[JobPosting]:
        if self._jobs_cache is not None:
            return self._jobs_cache
        payload = fetch_json(self.api_url, timeout=self.timeout, headers={"User-Agent": "Mozilla/5.0 (jobhunter)"})
        items = payload if isinstance(payload, list) else []
        # The first element is a legal notice, not a job.
        self._jobs_cache = [self._normalize_job(item) for item in items if isinstance(item, dict) and item.get("id")]
        return self._jobs_cache

    def _normalize_job(self, item: dict[str, Any]) -> JobPosting:
        posted_at = None
        raw_date = item.get("date")
        if raw_date:
            try:
                posted_at = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                posted_at = None
        tags = tuple(str(tag) for tag in item.get("tags") or [] if tag)
        salary = _format_salary(item.get("salary_min"), item.get("salary_max"))
        return JobPosting(
            source=self.name,
            source_id=str(item.get("id") or ""),
            title=unescape(str(item.get("position") or "")),
            company=unescape(str(item.get("company") or "")),
            url=str(item.get("url") or item.get("apply_url") or ""),
            location=str(item.get("location") or "") or "Remote",
            description=strip_html(str(item.get("description") or "")),
            tags=tags,
            salary=salary,
            posted_at=posted_at,
            raw=item,
        )


def _format_salary(minimum: Any, maximum: Any) -> str | None:
    try:
        low = int(minimum or 0)
        high = int(maximum or 0)
    except (TypeError, ValueError):
        return None
    if low and high:
        return f"${low}-${high} yearly"
    if low:
        return f"${low}+ yearly"
    if high:
        return f"up to ${high} yearly"
    return None
