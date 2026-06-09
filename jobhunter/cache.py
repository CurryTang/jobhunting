from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from jobhunter.agent import QueryPlanner, _diversify, _has_core_match, _has_excluded_term, has_location_mismatch, score_job
from jobhunter.details import enrich_jobs_with_details
from jobhunter.models import JobMatch, JobPosting, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.storage import job_key


class ProgressiveJobCache:
    """Query-driven local cache for source fetches, normalized jobs, and ranked matches."""

    def __init__(
        self,
        store: Any,
        platforms: Sequence[JobPlatform],
        *,
        planner: QueryPlanner | None = None,
        max_age_hours: int = 24,
        fetch_details: bool = False,
        detail_limit_per_fetch: int = 2,
        detail_total_limit: int = 10,
        detail_timeout: float = 3.0,
    ) -> None:
        self.store = store
        self.platforms = list(platforms)
        self.planner = planner or QueryPlanner()
        self.max_age_hours = max_age_hours
        self.fetch_details = fetch_details
        self.detail_limit_per_fetch = detail_limit_per_fetch
        self.detail_total_limit = detail_total_limit
        self.detail_timeout = detail_timeout
        self.errors: list[str] = []
        self.fetch_summaries: list[Any] = []

    def search_or_fetch(
        self,
        profile: UserProfile,
        *,
        limit: int = 10,
        per_query_limit: int = 20,
        max_queries: int | None = None,
    ) -> list[JobMatch]:
        queries = self.planner.plan(profile, max_queries=max_queries) if max_queries is not None else self.planner.plan(profile)
        self.errors = []
        self.fetch_summaries = []
        detail_remaining = self.detail_total_limit

        for query in queries:
            # Freshness and storage are keyed on the full query identity, not
            # just the text: a cached "ml engineer" fetch for Remote US must
            # not satisfy a later onsite New York run.
            query_identity = _query_identity(query, per_query_limit=per_query_limit)
            for platform in self.platforms:
                if self.store.has_fresh_source_query(
                    platform.name,
                    query_identity,
                    max_age_hours=self.max_age_hours,
                ):
                    continue
                try:
                    jobs = platform.search(query, profile, limit=per_query_limit)
                    if self.fetch_details and detail_remaining > 0:
                        detail_limit = min(self.detail_limit_per_fetch, detail_remaining)
                        jobs = enrich_jobs_with_details(jobs, limit=detail_limit, timeout=self.detail_timeout)
                        detail_remaining -= detail_limit
                except Exception as exc:  # pragma: no cover - live source behavior.
                    message = f"{platform.name} failed for query '{query.text}': {exc}"
                    self.errors.append(message)
                    self.fetch_summaries.append(
                        self.store.save_source_fetch(
                            source=platform.name,
                            query_text=query_identity,
                            jobs=[],
                            role_family=query.role,
                            location=query.location,
                            filters={"remote": query.remote, "skills": query.skills},
                            request={"query": query.text, "limit": per_query_limit},
                            status="error",
                            error=message,
                        )
                    )
                    continue
                self.fetch_summaries.append(
                    self.store.save_source_fetch(
                        source=platform.name,
                        query_text=query_identity,
                        jobs=jobs,
                        role_family=query.role,
                        location=query.location,
                        filters={"remote": query.remote, "skills": query.skills},
                        request={"query": query.text, "limit": per_query_limit},
                    )
                )

        cached_jobs = self.store.list_cached_jobs(
            sources=[platform.name for platform in self.platforms],
            limit=max(limit * 25, per_query_limit * max(len(queries), 1) * max(len(self.platforms), 1)),
        )
        return _rank_cached_jobs(cached_jobs, profile, queries, limit=limit)


def _rank_cached_jobs(
    jobs: Sequence[JobPosting],
    profile: UserProfile,
    queries,
    *,
    limit: int,
) -> list[JobMatch]:
    seen: dict[str, JobMatch] = {}
    for job in jobs:
        if has_location_mismatch(job, profile):
            continue
        if _has_excluded_term(job, profile):
            continue
        best: JobMatch | None = None
        for query in queries:
            match = score_job(job, profile, query)
            if match.score <= 0:
                continue
            if not _has_core_match(match, profile):
                continue
            if best is None or match.score > best.score:
                best = match
        if best is None:
            continue
        key = job_key(job)
        current = seen.get(key)
        if current is None or best.score > current.score:
            seen[key] = best
    return _diversify(
        sorted(seen.values(), key=lambda match: (-match.score, match.job.company, match.job.title)),
        limit=limit,
    )


def _query_identity(query, *, per_query_limit: int | None = None) -> str:
    parts = [query.text]
    if query.role:
        parts.append(f"role={query.role}")
    if query.skills:
        parts.append("skills=" + ",".join(query.skills))
    if query.location:
        parts.append(f"location={query.location}")
    if query.remote is not None:
        parts.append(f"remote={query.remote}")
    if per_query_limit is not None:
        # Fetch breadth is part of identity: a shallow cached fetch must not
        # satisfy a later, broader run.
        parts.append(f"limit={per_query_limit}")
    return " | ".join(parts)
