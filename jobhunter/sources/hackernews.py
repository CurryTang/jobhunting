from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform


class HackerNewsWhoIsHiringPlatform(JobPlatform):
    """Adapter over HN Algolia for Who's Hiring comments."""

    name = "hackernews"
    base_url = "https://hn.algolia.com/api/v1/search"
    story_search_url = "https://hn.algolia.com/api/v1/search_by_date"

    def __init__(self, *, timeout: float = 20.0) -> None:
        self.timeout = timeout
        self._who_is_hiring_story_id: str | None = None

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        story_id = self._latest_who_is_hiring_story_id()
        params = {
            "query": query.text,
            "tags": f"comment,story_{story_id}",
            "hitsPerPage": str(limit),
        }
        url = f"{self.base_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "jobhunter-demo/0.1 (+https://example.local)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        jobs = []
        for hit in payload.get("hits", []):
            text = _strip_html(str(hit.get("comment_text") or hit.get("story_text") or ""))
            if not _looks_like_job_comment(text):
                continue
            jobs.append(self._normalize_hit(hit, text))
        return jobs[:limit]

    def _latest_who_is_hiring_story_id(self) -> str:
        if self._who_is_hiring_story_id:
            return self._who_is_hiring_story_id
        params = {
            "query": "Ask HN: Who is hiring?",
            "tags": "story",
            "hitsPerPage": "20",
        }
        url = f"{self.story_search_url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "jobhunter-demo/0.1 (+https://example.local)"},
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        for hit in payload.get("hits", []):
            title = str(hit.get("title") or "")
            if re.search(r"^Ask HN:\s*Who is hiring\?", title, re.I):
                self._who_is_hiring_story_id = str(hit.get("objectID") or hit.get("id"))
                return self._who_is_hiring_story_id
        raise RuntimeError("could not find latest HN Who is Hiring thread")

    def _normalize_hit(self, hit: dict, text: str) -> JobPosting:
        source_id = str(hit.get("objectID") or hit.get("id") or "")
        created_at = None
        raw_created = hit.get("created_at_i")
        if raw_created:
            created_at = datetime.fromtimestamp(int(raw_created), tz=timezone.utc)
        company, title = _infer_company_title(text)
        return JobPosting(
            source=self.name,
            source_id=source_id,
            title=title,
            company=company,
            url=f"https://news.ycombinator.com/item?id={source_id}",
            location=_infer_location(text),
            description=text,
            tags=("who-is-hiring",),
            posted_at=created_at,
            raw=hit,
        )


def _strip_html(value: str) -> str:
    value = unescape(value)
    value = re.sub(r"<p\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    # Collapse spaces per line but keep newlines so the first line stays a
    # usable company/title header for _infer_company_title.
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.split("\n")]
    return "\n".join(line for line in lines if line).strip()


_SEEKER_PATTERNS = re.compile(
    r"^(i'?m\b|i am\b|hi[,!]? i\b)|\b(seeking work|seeking a role|looking for (a )?(job|work|role|position)|open to work|available for (hire|work|freelance))\b",
    re.I,
)


def _looks_like_job_comment(text: str) -> bool:
    first_line = text.split("\n")[0]
    if _SEEKER_PATTERNS.search(first_line):
        return False
    normalized = text.lower()
    return any(term in normalized for term in ("hiring", "remote", "engineer", "developer"))


def _infer_company_title(text: str) -> tuple[str, str]:
    first = text.split("\n")[0].strip()
    pieces = [piece.strip(" -|") for piece in re.split(r"\|| - | — ", first) if piece.strip()]
    company = pieces[0][:80] if pieces else "Unknown company"
    title = "Who is Hiring opportunity"
    for piece in pieces[1:]:
        if re.search(r"engineer|developer|scientist|designer|manager|founder", piece, re.I):
            title = piece[:120]
            break
    return company, title


def _infer_location(text: str) -> str | None:
    match = re.search(r"\b(remote|onsite|hybrid|[A-Z][a-z]+,\s*[A-Z]{2})\b", text)
    return match.group(0) if match else None
