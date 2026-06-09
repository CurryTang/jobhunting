from __future__ import annotations

import os
import urllib.error
import urllib.parse
from datetime import datetime
from typing import Any

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.common import fetch_json, filter_and_rank, strip_html

# Curated boards with a bias toward AI labs and strong engineering brands.
# Override with JOBHUNTER_GREENHOUSE_BOARDS="slug1,slug2" (comma-separated).
DEFAULT_BOARDS: tuple[str, ...] = (
    "anthropic",
    "deepmind",
    "xai",
    "scaleai",
    "databricks",
    "togetherai",
    "stripe",
    "figma",
)

_BOARD_DISPLAY_NAMES = {
    "deepmind": "Google DeepMind",
    "xai": "xAI",
    "scaleai": "Scale AI",
    "togetherai": "Together AI",
}


class GreenhousePlatform(JobPlatform):
    """Adapter over the public Greenhouse job-board API.

    One request per configured board per run; boards that 404 (renamed or
    moved off Greenhouse) are skipped silently so a stale slug never breaks
    the search.
    """

    name = "greenhouse"
    api_template = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

    def __init__(self, *, boards: tuple[str, ...] | None = None, timeout: float = 20.0) -> None:
        self.timeout = timeout
        env_boards = os.environ.get("JOBHUNTER_GREENHOUSE_BOARDS", "")
        self.boards = boards or tuple(part.strip() for part in env_boards.split(",") if part.strip()) or DEFAULT_BOARDS
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
        for board in self.boards:
            url = self.api_template.format(board=urllib.parse.quote(board))
            try:
                payload = fetch_json(url, timeout=self.timeout)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    continue
                raise
            company = _BOARD_DISPLAY_NAMES.get(board, board.replace("-", " ").title())
            for item in payload.get("jobs", []) if isinstance(payload, dict) else []:
                if isinstance(item, dict):
                    jobs.append(self._normalize_job(item, company=company))
        self._jobs_cache = jobs
        return self._jobs_cache

    def _normalize_job(self, item: dict[str, Any], *, company: str) -> JobPosting:
        location = ((item.get("location") or {}).get("name") if isinstance(item.get("location"), dict) else None) or None
        departments = [str(dep.get("name")) for dep in item.get("departments") or [] if isinstance(dep, dict) and dep.get("name")]
        # Only first_published is a real posting date. updated_at reflects
        # any board edit, and using it as posted_at would let the agent's
        # stale penalty wrongly demote open direct-board roles; it stays
        # available in raw.
        posted_at = _parse_datetime(item.get("first_published"))
        return JobPosting(
            source=self.name,
            source_id=str(item.get("id") or ""),
            title=str(item.get("title") or ""),
            company=company,
            url=str(item.get("absolute_url") or ""),
            location=location,
            description=strip_html(str(item.get("content") or ""))[:4000],
            tags=tuple(departments),
            posted_at=posted_at,
            raw={key: value for key, value in item.items() if key != "content"},
        )


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
