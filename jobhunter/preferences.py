from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from jobhunter.models import JobPreferences, UserProfile


@dataclass(frozen=True)
class PreferenceQuestion:
    id: str
    prompt: str
    field: str
    reason: str
    examples: tuple[str, ...] = ()


def adaptive_preference_questions(
    profile: UserProfile,
    preferences: JobPreferences | None = None,
    *,
    limit: int = 8,
) -> list[PreferenceQuestion]:
    """Return missing preference questions tailored to the current profile."""

    prefs = preferences or profile.preferences
    questions: list[PreferenceQuestion] = []
    highlight_examples = _portfolio_highlight_examples(profile)
    if not prefs.focus_highlights and len(highlight_examples) > 1:
        questions.append(
            PreferenceQuestion(
                id="focus_highlights",
                field="focus_highlights",
                prompt="Which portfolio strengths should I emphasize most?",
                reason="Your materials contain several strong points; choosing a focus improves query design and ranking.",
                examples=highlight_examples[:4],
            )
        )
    if not prefs.target_roles and len(profile.roles) > 1:
        questions.append(
            PreferenceQuestion(
                id="target_roles",
                field="target_roles",
                prompt="Which roles should I prioritize?",
                reason="Your profile supports multiple role tracks.",
                examples=profile.roles[:4],
            )
        )
    if not prefs.job_types:
        questions.append(
            PreferenceQuestion(
                id="job_types",
                field="job_types",
                prompt="Are you looking for full-time roles, internships, or both?",
                reason="This decides whether internships are included. Full-time is assumed when unanswered, with internships ranked lower.",
                examples=("full-time", "internship", "both"),
            )
        )
    if not prefs.preferred_locations:
        questions.append(
            PreferenceQuestion(
                id="preferred_locations",
                field="preferred_locations",
                prompt="Where do you want to work?",
                reason="Location affects source queries and ranking.",
                examples=("Remote US", "San Francisco", "New York", "Seattle"),
            )
        )
    if prefs.remote is None:
        questions.append(
            PreferenceQuestion(
                id="remote",
                field="remote",
                prompt="Are remote roles acceptable or preferred?",
                reason="Remote preference is a strong filter for startup boards.",
                examples=("remote preferred", "hybrid ok", "onsite only"),
            )
        )
    if not prefs.company_stages:
        questions.append(
            PreferenceQuestion(
                id="company_stages",
                field="company_stages",
                prompt="What company stages do you prefer?",
                reason="Startup boards expose stage and funding signals.",
                examples=("seed", "series a", "growth", "public-company ok"),
            )
        )
    if not prefs.industries:
        questions.append(
            PreferenceQuestion(
                id="industries",
                field="industries",
                prompt="Which industries or domains should I favor?",
                reason="Domain preferences help rank broad engineering roles.",
                examples=("AI", "developer tools", "healthcare", "fintech"),
            )
        )
    if prefs.result_count is None:
        questions.append(
            PreferenceQuestion(
                id="result_count",
                field="result_count",
                prompt="How many jobs should I return?",
                reason="Result count controls search breadth and how much detail to include.",
                examples=("10", "25", "50"),
            )
        )
    if prefs.output_format is None:
        questions.append(
            PreferenceQuestion(
                id="output_format",
                field="output_format",
                prompt="What output format should I use? TSV is the default.",
                reason="TSV is the default because it is easy to paste into spreadsheets and databases.",
                examples=("tsv", "json", "markdown"),
            )
        )
    if prefs.min_salary is None:
        questions.append(
            PreferenceQuestion(
                id="min_salary",
                field="min_salary",
                prompt="What minimum base salary should I use when available?",
                reason="Some platforms expose salary ranges.",
                examples=("$120000", "$160000", "no minimum"),
            )
        )
    if prefs.visa_sponsorship is None:
        questions.append(
            PreferenceQuestion(
                id="visa_sponsorship",
                field="visa_sponsorship",
                prompt="Do you need visa sponsorship?",
                reason="Some postings include visa constraints.",
                examples=("yes", "no"),
            )
        )
    return questions[:limit]


def load_preferences(path: str | Path) -> JobPreferences:
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    return preferences_from_mapping(data)


def save_preferences(path: str | Path, preferences: JobPreferences) -> None:
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(preferences), indent=2, sort_keys=True), encoding="utf-8")


def preferences_from_mapping(data: dict[str, Any]) -> JobPreferences:
    return JobPreferences(
        target_roles=_tuple_value(data.get("target_roles")),
        preferred_locations=_tuple_value(data.get("preferred_locations")),
        remote=_bool_value(data.get("remote")),
        job_types=_tuple_value(data.get("job_types")),
        company_stages=_tuple_value(data.get("company_stages")),
        industries=_tuple_value(data.get("industries")),
        min_salary=_int_value(data.get("min_salary")),
        visa_sponsorship=_bool_value(data.get("visa_sponsorship")),
        sources=_tuple_value(data.get("sources")),
        excluded_terms=_tuple_value(data.get("excluded_terms")),
        focus_highlights=_tuple_value(data.get("focus_highlights")),
        result_count=_int_value(data.get("result_count")),
        output_format=_format_value(data.get("output_format")),
        notes=data.get("notes") if data.get("notes") else None,
    )


def update_preferences(preferences: JobPreferences, answers: dict[str, Any]) -> JobPreferences:
    data = asdict(preferences)
    for key, value in answers.items():
        if key not in data:
            raise ValueError(f"unknown preference field: {key}")
        data[key] = value
    return preferences_from_mapping(data)


def parse_preference_assignment(value: str) -> tuple[str, Any]:
    if "=" not in value:
        raise ValueError("preference assignments must use key=value")
    key, raw = value.split("=", 1)
    key = key.strip()
    raw = raw.strip()
    if key in {"remote", "visa_sponsorship"}:
        return key, _bool_value(raw)
    if key in {"min_salary", "result_count"}:
        return key, _int_value(raw)
    if key == "output_format":
        return key, _format_value(raw)
    if key == "notes":
        return key, raw
    return key, _tuple_value(raw)


def _tuple_value(value: Any) -> tuple[str, ...]:
    if value is None or value == "":
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return (str(value),)


def _bool_value(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"yes", "y", "true", "1", "remote", "remote preferred"}:
        return True
    if normalized in {"no", "n", "false", "0", "onsite", "onsite only"}:
        return False
    return None


def _int_value(value: Any) -> int | None:
    if value is None or value == "":
        return None
    digits = "".join(ch for ch in str(value) if ch.isdigit())
    return int(digits) if digits else None


def _format_value(value: Any) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower()
    if normalized in {"tsv", "json", "markdown", "md"}:
        return "markdown" if normalized == "md" else normalized
    return "tsv"


def _portfolio_highlight_examples(profile: UserProfile) -> tuple[str, ...]:
    highlights = profile.evidence.get("portfolio_highlights") if profile.evidence else None
    if not isinstance(highlights, list):
        return ()
    examples: list[str] = []
    for item in highlights:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        text = _compact_highlight_example(item["text"], profile=profile)
        examples.append(text)
    return tuple(examples)


def _compact_highlight_example(text: str, *, profile: UserProfile) -> str:
    text = " ".join(text.replace(".pdf)", "").split())
    if text.startswith("Repository: "):
        parts = [part.strip() for part in text.split(";") if part.strip()]
        name = parts[0].replace("Repository:", "").strip()
        description = ""
        for part in parts:
            if part.startswith("Description:"):
                description = part.replace("Description:", "").strip()
                break
        text = f"{name}: {description}" if description else name
    if "? " in text:
        text = text.split("? ", 1)[0] + "?"
    elif profile.name and f" {profile.name} " in text:
        text = text.split(f" {profile.name} ", 1)[0].strip()
    else:
        author_match = re.search(r"\s+[A-Z][a-z]+\s+[A-Z][a-z]+,\s*$", text)
        if author_match and author_match.start() > 35:
            text = text[: author_match.start()].strip()
    trailing_author = re.search(r"\s+[A-Z][a-z]+\s+[A-Z][a-z]+,\s*$", text)
    if trailing_author and trailing_author.start() > 35:
        text = text[: trailing_author.start()].strip()
    if ";" in text:
        text = text.split(";", 1)[0].strip()
    if len(text) > 110:
        text = text[:107].rstrip() + "..."
    return text
