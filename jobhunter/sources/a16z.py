from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import filter_and_rank


class A16ZPlatform(JobPlatform):
    """Adapter for the public a16z/Consider portfolio jobs endpoint."""

    name = "a16z"
    search_url = "https://jobs.a16z.com/api-boards/search-jobs"
    board_id = "andreessen-horowitz"

    def __init__(self, *, timeout: float = 20.0, fetch_size: int = 50) -> None:
        self.timeout = timeout
        self.fetch_size = fetch_size
        self._jobs_cache: list[JobPosting] | None = None

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        # The endpoint is queried with an empty filter (it returns the board
        # head regardless), so fetch once per run and filter locally so each
        # generated query surfaces different relevant postings.
        jobs = self._fetch_all_jobs()
        matched = filter_and_rank(jobs, query, limit=limit)
        return matched or jobs[:limit]

    def _fetch_all_jobs(self) -> list[JobPosting]:
        if self._jobs_cache is not None:
            return self._jobs_cache
        payload = {
            "meta": {"size": min(max(self.fetch_size, 50), 50)},
            "board": {"id": self.board_id, "isParent": True},
            "query": {},
            "grouped": False,
            "parentSlug": self.board_id,
        }
        request = urllib.request.Request(
            self.search_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://jobs.a16z.com",
                "Referer": "https://jobs.a16z.com/jobs",
                "User-Agent": "jobhunter-demo/0.1 (+https://example.local)",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        self._jobs_cache = [self._normalize_job(job) for job in data.get("jobs", [])]
        return self._jobs_cache

    def _normalize_job(self, job: dict[str, Any]) -> JobPosting:
        salary = _format_salary(job.get("salary"))
        tags = tuple(
            dict.fromkeys(
                [
                    *_labels(job.get("jobTypes")),
                    *_labels(job.get("jobFunctions")),
                    *_labels(job.get("stages")),
                    *_labels(job.get("markets")),
                    *[str(skill) for skill in job.get("skills") or []],
                    *[str(skill) for skill in job.get("requiredSkills") or []],
                    *[str(skill) for skill in job.get("preferredSkills") or []],
                ]
            )
        )
        locations = job.get("locations") or []
        description_parts = [
            job.get("description"),
            " ".join(str(item) for item in job.get("departments") or []),
            " ".join(tags),
        ]
        return JobPosting(
            source=self.name,
            source_id=str(job.get("jobId") or job.get("url") or job.get("applyUrl") or ""),
            title=str(job.get("title") or ""),
            company=str(job.get("companyName") or ""),
            url=str(job.get("applyUrl") or job.get("url") or ""),
            location=" / ".join(str(location) for location in locations if location) or None,
            description=" ".join(str(part) for part in description_parts if part),
            tags=tags,
            salary=salary,
            posted_at=_parse_timestamp(job.get("timeStamp")),
            raw=job,
        )


def _labels(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    labels = []
    for value in values:
        if isinstance(value, dict):
            labels.append(str(value.get("label") or value.get("value") or value.get("id") or ""))
        elif value:
            labels.append(str(value))
    return [label for label in labels if label]


def _format_salary(salary: Any) -> str | None:
    if not isinstance(salary, dict):
        return None
    min_value = salary.get("minValue")
    max_value = salary.get("maxValue")
    currency = (salary.get("currency") or {}).get("label") or ""
    period = (salary.get("period") or {}).get("label") or ""
    if min_value and max_value:
        return f"{currency} {min_value}-{max_value} / {period}".strip()
    if min_value:
        return f"{currency} {min_value}+ / {period}".strip()
    if max_value:
        return f"up to {currency} {max_value} / {period}".strip()
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, (int, float)):
        # Consider payloads sometimes carry epoch values (seconds or millis).
        seconds = value / 1000 if value > 1e11 else value
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
