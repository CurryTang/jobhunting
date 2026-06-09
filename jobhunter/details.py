from __future__ import annotations

import re
import urllib.request
from dataclasses import replace
from html.parser import HTMLParser
from typing import Iterable

from jobhunter.models import JobPosting


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._skip = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip = False

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._chunks.append(text)

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self._chunks)).strip()


def enrich_jobs_with_details(
    jobs: Iterable[JobPosting],
    *,
    limit: int = 25,
    timeout: float = 10.0,
    max_chars: int = 12000,
) -> list[JobPosting]:
    enriched: list[JobPosting] = []
    remaining = limit
    for job in jobs:
        if remaining <= 0 or not job.url:
            enriched.append(job)
            continue
        detail_text = fetch_detail_text(job.url, timeout=timeout, max_chars=max_chars)
        if not detail_text:
            enriched.append(job)
            continue
        raw = dict(job.raw)
        raw["detail_text"] = detail_text
        raw["detail_url"] = job.url
        description = job.description
        if len(detail_text) > len(description):
            description = detail_text
        enriched.append(replace(job, description=description, raw=raw))
        remaining -= 1
    return enriched


def fetch_detail_text(url: str, *, timeout: float = 10.0, max_chars: int = 12000) -> str:
    if not url.startswith(("http://", "https://")):
        return ""
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "jobhunter-detail-fetcher/0.1 (+https://example.local)"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("content-type", "")
            body = response.read(max_chars * 4).decode("utf-8", errors="replace")
    except Exception:
        return ""
    if "html" in content_type.lower() or "<html" in body[:500].lower():
        parser = _HTMLTextExtractor()
        parser.feed(body)
        return parser.text[:max_chars]
    return re.sub(r"\s+", " ", body).strip()[:max_chars]
