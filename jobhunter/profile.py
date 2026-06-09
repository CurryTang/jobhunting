from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from jobhunter.models import JobPreferences, UserProfile

DEFAULT_SKILLS = (
    "python",
    "typescript",
    "javascript",
    "react",
    "node",
    "go",
    "rust",
    "java",
    "sql",
    "postgres",
    "mysql",
    "mongodb",
    "redis",
    "aws",
    "gcp",
    "azure",
    "docker",
    "kubernetes",
    "terraform",
    "pytorch",
    "tensorflow",
    "machine learning",
    "deep learning",
    "llm",
    "nlp",
    "data science",
    "analytics",
    "backend",
    "frontend",
    "full stack",
    "distributed systems",
    "security",
    "graph",
    "graphs",
    "graph neural networks",
    "relational deep learning",
    "relational foundation models",
    "relational in-context learning",
    "tabular data",
    "jupyter",
    "latex",
    "mlsys",
    "dl infra",
    "deep learning infrastructure",
    "llm inference",
    "post-training",
    "long context",
    "long context modeling",
    "agentic",
    "agents",
    "agentic memory",
    "memory systems",
    "proactive agents",
    "multi-agent",
    "ai agents",
    "gpu",
    "optimization",
    "forecasting",
    "research",
)

ROLE_PATTERNS = (
    "software engineer",
    "backend engineer",
    "frontend engineer",
    "full stack engineer",
    "machine learning engineer",
    "data scientist",
    "data engineer",
    "research engineer",
    "research scientist",
    "machine learning researcher",
    "ai researcher",
    "product manager",
    "devops engineer",
    "platform engineer",
    "security engineer",
)

LOCATION_PATTERNS = (
    "remote",
    "united states",
    "usa",
    "canada",
    "new york",
    "san francisco",
    "bay area",
    "seattle",
    "austin",
    "boston",
    "chicago",
    "los angeles",
    "michigan",
    "east lansing",
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._chunks.append(text)

    @property
    def text(self) -> str:
        return " ".join(self._chunks)


def load_input(value: str, *, timeout: float = 15.0) -> str:
    """Load resume/homepage/GitHub/raw text input into plain text."""

    value = value.strip()
    if not value:
        raise ValueError("input is empty")

    parsed = urllib.parse.urlparse(value)
    if parsed.scheme in {"http", "https"}:
        if _is_github_profile_url(parsed):
            return _load_github_profile(parsed, timeout=timeout)
        return _load_url_text(value, timeout=timeout)

    path = Path(value).expanduser()
    if path.exists():
        if path.suffix.lower() == ".json":
            return _json_to_text(json.loads(path.read_text(encoding="utf-8")))
        return path.read_text(encoding="utf-8")

    return value


def build_user_profile(raw_text: str, *, preferences: JobPreferences | None = None) -> UserProfile:
    """Build a structured candidate profile with transparent heuristics."""

    highlights = _extract_portfolio_highlights(raw_text)
    highlight_text = "\n".join(item["text"] for item in highlights)
    analysis_text = "\n".join(part for part in (highlight_text, raw_text) if part)
    normalized = _normalize(analysis_text)
    links = tuple(dict.fromkeys(re.findall(r"https?://[^\s)>\"]+", raw_text)))
    roles = _find_terms(normalized, ROLE_PATTERNS)
    skills = _find_terms(normalized, DEFAULT_SKILLS)
    roles = _merge_preserving_order(roles, _infer_roles_from_skills(skills, normalized))
    locations = _expand_locations(_find_terms(normalized, LOCATION_PATTERNS))
    seniority = _infer_seniority(normalized)
    name = _infer_name(raw_text)
    headline = _infer_headline(raw_text, roles)
    excluded_keywords = set(skills) | set(roles)
    for phrase in (*skills, *roles):
        excluded_keywords.update(phrase.split())
    if name:
        excluded_keywords.update(part.lower() for part in name.split())
    excluded_keywords.update(_proper_name_tokens(raw_text))
    excluded_keywords.update(locations)
    for location in locations:
        excluded_keywords.update(location.split())
    highlight_keywords = _top_keywords(_normalize(highlight_text), exclude=excluded_keywords, limit=12)
    keywords = _merge_preserving_order(highlight_keywords, _top_keywords(normalized, exclude=excluded_keywords))

    return UserProfile(
        raw_text=raw_text,
        name=name,
        headline=headline,
        roles=tuple(roles),
        skills=tuple(skills),
        locations=tuple(locations),
        links=links,
        seniority=seniority,
        keywords=tuple(keywords),
        preferences=preferences or JobPreferences(),
        evidence={
            "heuristics": {
                "roles": list(roles),
                "skills": list(skills),
                "locations": list(locations),
                "seniority": seniority,
            },
            "portfolio_highlights": highlights,
        },
    )


def _load_url_text(url: str, *, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "jobhunter-demo/0.1 (+https://example.local)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("content-type", "")
        body = response.read().decode("utf-8", errors="replace")
    if "html" in content_type.lower() or "<html" in body[:500].lower():
        parser = _TextExtractor()
        parser.feed(body)
        return parser.text
    return body


def _is_github_profile_url(parsed: urllib.parse.ParseResult) -> bool:
    host = parsed.netloc.lower()
    parts = [part for part in parsed.path.split("/") if part]
    return host == "github.com" and len(parts) == 1


def _load_github_profile(parsed: urllib.parse.ParseResult, *, timeout: float) -> str:
    username = parsed.path.strip("/")
    try:
        data = _github_get_json(f"https://api.github.com/users/{urllib.parse.quote(username)}", timeout=timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return _load_url_text(urllib.parse.urlunparse(parsed), timeout=timeout)

    fields = [
        data.get("name"),
        data.get("bio"),
        data.get("company"),
        data.get("location"),
        data.get("blog"),
        data.get("html_url"),
    ]
    profile_readme = _load_github_profile_readme(username, timeout=timeout)
    if profile_readme:
        fields.append("GitHub profile self-introduction:")
        fields.append(profile_readme)
    fields.extend(_load_github_repo_text(username, timeout=timeout))
    return "\n".join(str(field) for field in fields if field)


def _github_get_json(url: str, *, timeout: float) -> object:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "jobhunter-demo/0.1 (+https://example.local)"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_github_profile_readme(username: str, *, timeout: float) -> str | None:
    encoded_username = urllib.parse.quote(username)
    url = f"https://api.github.com/repos/{encoded_username}/{encoded_username}/readme"
    try:
        data = _github_get_json(url, timeout=timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("content"), str):
        return None
    try:
        body = base64.b64decode(data["content"]).decode("utf-8", errors="replace")
    except (ValueError, LookupError):
        return None
    return _markdown_to_text(body)


def _load_github_repo_text(username: str, *, timeout: float, limit: int = 30) -> list[str]:
    repo_url = (
        "https://api.github.com/users/"
        f"{urllib.parse.quote(username)}/repos?sort=pushed&per_page={limit}"
    )
    try:
        repos = _github_get_json(repo_url, timeout=timeout)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
        return []
    if not isinstance(repos, list):
        return []

    lines = ["Recent public GitHub repositories, sorted by pushed time:"]
    languages: dict[str, int] = {}
    topics: dict[str, int] = {}
    for repo in repos:
        if not isinstance(repo, dict) or repo.get("fork"):
            continue
        name = repo.get("name")
        description = repo.get("description")
        language = repo.get("language")
        repo_topics = repo.get("topics") or []
        if language:
            languages[str(language)] = languages.get(str(language), 0) + 1
        for topic in repo_topics:
            topics[str(topic)] = topics.get(str(topic), 0) + 1
        parts = [f"Repository: {name}"]
        if language:
            parts.append(f"Language: {language}")
        if description:
            parts.append(f"Description: {description}")
        if repo.get("pushed_at"):
            parts.append(f"Pushed: {repo.get('pushed_at')}")
        if repo.get("updated_at"):
            parts.append(f"Updated: {repo.get('updated_at')}")
        if repo_topics:
            parts.append("Topics: " + ", ".join(str(topic) for topic in repo_topics))
        lines.append("; ".join(part for part in parts if part))

    if languages:
        ordered = sorted(languages.items(), key=lambda item: (-item[1], item[0]))
        lines.append("GitHub languages: " + ", ".join(language for language, _ in ordered))
    if topics:
        ordered_topics = sorted(topics.items(), key=lambda item: (-item[1], item[0]))
        lines.append("GitHub topics: " + ", ".join(topic for topic, _ in ordered_topics[:20]))
    return lines


def _json_to_text(data: object) -> str:
    if isinstance(data, dict):
        return "\n".join(f"{key}: {_json_to_text(value)}" for key, value in data.items())
    if isinstance(data, list):
        return "\n".join(_json_to_text(item) for item in data)
    return "" if data is None else str(data)


def _markdown_to_text(value: str) -> str:
    value = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"[*_~>#]+", " ", value)
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"[ \t]+", " ", value).strip()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _extract_portfolio_highlights(text: str, *, limit: int = 10) -> list[dict[str, object]]:
    """Extract high-signal profile lines without assuming a specific person's domain."""

    candidates: list[tuple[float, int, str, list[str]]] = []
    section_score = 0.0
    parent_section_score = 0.0
    stale_section = False
    parent_stale_section = False
    for index, raw_line in enumerate(text.splitlines()):
        line = _clean_highlight_line(raw_line)
        if not line:
            continue
        line_norm = _normalize(line)
        if _looks_like_heading(line):
            heading_score = _section_salience(line_norm)
            heading_stale = _is_stale_context(line_norm)
            if _is_subsection_heading(line_norm):
                section_score = parent_section_score + heading_score
                stale_section = parent_stale_section or heading_stale
            else:
                parent_section_score = heading_score
                parent_stale_section = heading_stale
                section_score = heading_score
                stale_section = heading_stale
            continue

        score = section_score
        reasons: list[str] = []
        if stale_section:
            score -= 3.0
            reasons.append("stale_or_deprecated_section")
        line_score, line_reasons = _line_salience(line_norm)
        score += line_score
        reasons.extend(line_reasons)
        if score <= 0 or len(line) < 35 or _is_generic_highlight_line(line_norm):
            continue
        candidates.append((score, index, line, reasons))

    ranked = sorted(candidates, key=lambda item: (-item[0], item[1]))
    highlights: list[dict[str, object]] = []
    seen: set[str] = set()
    for score, _, line, reasons in ranked:
        key = _normalize(line)
        if key in seen:
            continue
        seen.add(key)
        highlights.append({"text": line, "score": round(score, 2), "reasons": reasons[:5]})
        if len(highlights) >= limit:
            break
    return highlights


def _clean_highlight_line(line: str) -> str:
    line = line.strip(" \t-*•")
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def _looks_like_heading(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) > 120:
        return False
    if re.match(r"^\d+[\).]\s+", stripped):
        return True
    words = stripped.split()
    if 1 <= len(words) <= 8 and sum(word[:1].isupper() for word in words) >= max(1, len(words) // 2):
        return True
    return bool(re.search(r"\b(20\d{2}\s*-\s*(present|20\d{2})|present|publications|projects|experience|research)\b", stripped, re.I))


def _section_salience(line_norm: str) -> float:
    score = 0.0
    ordinal = re.match(r"^(\d+)[\).]\s+", line_norm)
    if ordinal:
        position = int(ordinal.group(1))
        if position == 1:
            score += 2.0
        elif position == 2:
            score += 1.0
    if re.search(r"\b(current|present|recent|now|new directions)\b", line_norm):
        score += 3.0
    year_matches = [int(year) for year in re.findall(r"\b(20\d{2})\b", line_norm)]
    if year_matches:
        latest = max(year_matches)
        current_year = date.today().year
        if latest >= current_year:
            score += 2.0
        elif latest >= current_year - 2:
            score += 1.0
    if re.search(r"\b(publications?|papers?|projects?|experience|research|writing|selected)\b", line_norm):
        score += 1.0
    if _is_stale_context(line_norm):
        score -= 3.0
    return score


def _is_subsection_heading(line_norm: str) -> bool:
    return bool(re.fullmatch(r"(publications?|papers?|projects?|writings?|selected work|selected projects)", line_norm))


def _line_salience(line_norm: str) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    signal_patterns = (
        (r"\b(current|present|recent|new directions)\b", 2.0, "current_or_recent"),
        (r"\b(20\d{2})\b", 0.75, "dated_work"),
        (r"\b(arxiv|neurips|iclr|icml|kdd|acl|emnlp|cvpr|sigir|www|spotlight|oral|poster|preprint)\b", 2.0, "publication_or_venue"),
        (r"\b(project|built|build|system|framework|platform|assistant|bot|tool|infrastructure|benchmark)\b", 1.25, "project_or_system"),
        (r"\b(first author|lead|founder|maintainer|award|accepted|published)\b", 1.5, "ownership_or_impact"),
        (r"\b(optimization|inference|agent|agents|memory|long context|forecasting|modeling|data|research)\b", 1.0, "technical_relevance"),
    )
    for pattern, weight, reason in signal_patterns:
        if re.search(pattern, line_norm):
            score += weight
            reasons.append(reason)
    if _is_stale_context(line_norm):
        score -= 4.0
        reasons.append("stale_or_deprecated_line")
    if re.search(r"\b(note|past|previously)\b", line_norm):
        score -= 0.75
    return score, reasons


def _is_stale_context(line_norm: str) -> bool:
    return bool(
        re.search(
            r"\b(past|previous|old|deprecated|not maintained|won't be maintained|will not be maintained|don't recommend|do not recommend)\b",
            line_norm,
        )
    )


def _is_generic_highlight_line(line_norm: str) -> bool:
    if len(line_norm) > 80:
        return False
    technical_terms = (
        "agent",
        "memory",
        "model",
        "system",
        "benchmark",
        "infrastructure",
        "optimization",
        "forecast",
        "data",
        "llm",
        "gpu",
        "research",
    )
    if any(term in line_norm for term in technical_terms):
        return False
    return bool(
        re.search(
            r"\b(currently working|working on|new directions|more coming|to be updated|coming soon)\b",
            line_norm,
        )
    )


def _find_terms(normalized: str, terms: Iterable[str]) -> list[str]:
    found: list[tuple[int, int, str]] = []
    for term in terms:
        escaped = re.escape(term.lower()).replace(r"\ ", r"[-\s]+")
        pattern = r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])"
        match = re.search(pattern, normalized)
        if match:
            found.append((match.start(), -len(term), term))
    return [term for _, _, term in sorted(found)]


def _merge_preserving_order(primary: list[str], secondary: list[str]) -> list[str]:
    return list(dict.fromkeys([*primary, *secondary]))


def _infer_roles_from_skills(skills: list[str], normalized: str) -> list[str]:
    skill_set = set(skills)
    roles: list[str] = []
    if {"agentic memory", "long context", "proactive agents", "research"} & skill_set:
        roles.append("research scientist")
    if {"llm", "graph", "graphs", "mlsys", "dl infra", "pytorch", "machine learning", "deep learning"} & skill_set:
        roles.append("machine learning engineer")
    if {"agentic", "agents", "gpu", "javascript", "node", "backend", "java"} & skill_set:
        roles.append("software engineer")
    if {"research", "llm", "agentic memory", "long context", "relational deep learning", "graph", "graphs"} & skill_set or "academic papers" in normalized:
        roles.append("research engineer")
    return roles


def _expand_locations(locations: list[str]) -> list[str]:
    expanded = list(locations)
    if {"michigan", "east lansing"} & set(locations) and "united states" not in expanded:
        expanded.append("united states")
    return expanded


def _infer_seniority(normalized: str) -> str | None:
    if re.search(r"\b(principal|staff|lead)\b", normalized):
        return "staff+"
    if re.search(r"\b(senior|sr\.)\b", normalized):
        return "senior"
    if re.search(r"\b(seeking|looking for|want|wants|open to)\b.{0,30}\b(intern|internship)\b", normalized):
        return "intern"
    if re.search(r"\b(intern|internship)\b", normalized) and not re.search(r"\b(phd|ph\.d|doctoral|postdoc|professor|faculty)\b", normalized):
        return "intern"
    if re.search(r"\b(junior|entry[- ]level|new grad)\b", normalized):
        return "junior"
    return None


def _infer_name(text: str) -> str | None:
    for line in text.splitlines():
        stripped = line.strip("# \t")
        if not stripped or "@" in stripped or "http" in stripped.lower():
            continue
        words = stripped.split()
        if 1 < len(words) <= 4 and all(word[:1].isupper() for word in words if word[:1].isalpha()):
            return stripped
        break
    return None


def _infer_headline(text: str, roles: list[str]) -> str | None:
    if roles:
        return roles[0].title()
    for line in text.splitlines():
        stripped = line.strip("# \t")
        if stripped and len(stripped) <= 100:
            return stripped
    return None


def _top_keywords(normalized: str, *, exclude: set[str], limit: int = 20) -> list[str]:
    stop = {
        "and",
        "the",
        "for",
        "with",
        "from",
        "that",
        "this",
        "have",
        "has",
        "are",
        "was",
        "were",
        "you",
        "your",
        "job",
        "work",
        "experience",
        "built",
        "developed",
        "focused",
        "looking",
        "github",
        "https",
        "com",
        "example",
        "remote",
        "roles",
        "repository",
        "repositories",
        "language",
        "languages",
        "description",
        "topics",
        "public",
        "state",
        "university",
        "pushed",
        "updated",
        "code",
        "paper",
        "papers",
        "publication",
        "publications",
        "preprint",
        "arxiv",
        "pdf",
        "currently",
        "present",
    }
    counts: dict[str, int] = {}
    for token in re.findall(r"[a-z][a-z0-9+#-]{2,}", normalized):
        if token in stop or token in exclude or any(char.isdigit() for char in token):
            continue
        counts[token] = counts.get(token, 0) + 1
    return [term for term, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def _proper_name_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in re.finditer(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3}\b", text):
        phrase = match.group(0)
        if phrase in {"Machine Learning", "Deep Learning", "Large Language Models", "United States"}:
            continue
        tokens.update(part.lower() for part in phrase.split())
    return tokens
