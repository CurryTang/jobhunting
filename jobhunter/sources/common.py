from __future__ import annotations

import json
import re
import urllib.request
from html import unescape
from typing import Any

from jobhunter.models import JobPosting, SearchQuery

USER_AGENT = "jobhunter-demo/0.1 (+https://example.local)"


def fetch_json(url: str, *, timeout: float, headers: dict[str, str] | None = None) -> Any:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def matches_query(job: JobPosting, query: SearchQuery) -> bool:
    """Local relevance filter for board-style sources that ignore queries."""

    return _relevance(job, _query_terms(query)) > 0


def filter_and_rank(jobs: list[JobPosting], query: SearchQuery, *, limit: int) -> list[JobPosting]:
    """Filter a full board by query relevance and rank before truncating.

    Without ranking, `[:limit]` would return the board's arbitrary head
    (often alphabetical) instead of the most relevant postings.
    """

    terms = _query_terms(query)
    scored = [(score, job) for job in jobs if (score := _relevance(job, terms)) > 0]
    scored.sort(key=lambda pair: -pair[0])
    return [job for _, job in scored[:limit]]


def _query_terms(query: SearchQuery) -> set[str]:
    terms = {term.lower() for term in (query.role or "", *query.skills) if term}
    terms.update(token for token in query.text.lower().split() if len(token) > 2)
    return terms


def _relevance(job: JobPosting, terms: set[str]) -> int:
    title = job.title.lower()
    body = " ".join((job.company, job.description, " ".join(job.tags))).lower()
    title_hits = sum(1 for term in terms if term in title)
    body_hits = sum(1 for term in terms if term in body)
    # A lone term buried in the description (e.g. "research" inside an
    # Account Executive posting) is not a match: require a title hit or at
    # least two distinct body hits.
    if title_hits == 0 and body_hits < 2:
        return 0
    return title_hits * 3 + body_hits


def strip_html(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"<(script|style).*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()
