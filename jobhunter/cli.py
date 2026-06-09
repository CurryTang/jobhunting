from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

from jobhunter.agent import AgenticQueryPlanner, JobSearchAgent
from jobhunter.cache import ProgressiveJobCache
from jobhunter.graph import KuzuJobGraphStore, apply_graph_boosts
from jobhunter.models import JobPreferences
from jobhunter.outreach import build_outreach_message, resolve_apply_url
from jobhunter.preferences import (
    adaptive_preference_questions,
    load_preferences,
    parse_preference_assignment,
    save_preferences,
    update_preferences,
)
from jobhunter.profile import build_user_profile, load_input
from jobhunter.sources import (
    JobPlatform,
    OfflineDemoPlatform,
    build_platforms,
)
from jobhunter.storage import create_job_store
from jobhunter.trace import TrajectoryLogger


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the jobhunter demo search agent.")
    parser.add_argument("--input", required=True, help="Resume text/file path/homepage URL/GitHub profile URL.")
    parser.add_argument("--sources", default="remotive", help="Comma-separated sources: remotive,hackernews.")
    parser.add_argument("--offline", action="store_true", help="Use deterministic offline sample jobs.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum ranked jobs to print.")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a compact text table.")
    parser.add_argument(
        "--store-url",
        help=(
            "Optional database URL used to persist deduplicated jobs and search runs. "
            "Defaults to JOBHUNTER_DATABASE_URL when set; storage stays disabled otherwise."
        ),
    )
    parser.add_argument("--store-db", help="Development-only SQLite path for local storage tests.")
    parser.add_argument(
        "--progressive-cache",
        action="store_true",
        help="Use the configured store as a progressive source cache before ranking.",
    )
    parser.add_argument("--graph-db", help="Kuzu graph database path used to project matches and apply graph boosts.")
    parser.add_argument("--agentic-search", action="store_true", help="Use a broad role-family query plan for recall-heavy search.")
    parser.add_argument("--max-queries", type=int, help="Maximum generated queries to run. Useful for smoke tests or bounded recall.")
    parser.add_argument("--fetch-details", action="store_true", help="Fetch and store detail-page text for newly fetched jobs.")
    parser.add_argument("--per-query-limit", type=int, default=20, help="Maximum jobs requested from each source for each generated query.")
    parser.add_argument("--detail-limit", type=int, default=10, help="Maximum detail pages fetched per run when --fetch-details is set.")
    parser.add_argument("--detail-timeout", type=float, default=3.0, help="Timeout in seconds for each detail-page request.")
    parser.add_argument("--preferences-file", help="JSON file used to load and record user job preferences.")
    parser.add_argument(
        "--set-preference",
        action="append",
        default=[],
        help="Record a preference answer as key=value. Repeat for multiple answers.",
    )
    parser.add_argument("--show-questions", action="store_true", help="Show adaptive missing-preference questions.")
    parser.add_argument(
        "--trajectory-log",
        help="JSONL file that records the search trajectory: profile, queries, per-source fetches, errors, and ranked results.",
    )
    args = parser.parse_args(argv)

    tracer = TrajectoryLogger(args.trajectory_log)
    raw = load_input(args.input)
    preferences = _load_and_update_preferences(args.preferences_file, args.set_preference)
    profile = build_user_profile(raw, preferences=preferences)
    tracer.log(
        "profile_built",
        input_ref=args.input,
        name=profile.name,
        headline=profile.headline,
        roles=list(profile.roles),
        skills=list(profile.skills),
        locations=list(profile.locations),
        seniority=profile.seniority,
        preferences=asdict(profile.preferences),
    )
    questions = adaptive_preference_questions(profile, preferences)
    platforms = [OfflineDemoPlatform()] if args.offline else _build_platforms(args.sources)
    result_limit = preferences.result_count or args.limit
    storage_summary = None
    store_url = _resolve_store_url(args.store_url, args.store_db)
    store = create_job_store(store_url) if store_url else None
    planner = AgenticQueryPlanner() if args.agentic_search else None
    if args.progressive_cache:
        if store is None:
            raise SystemExit("--progressive-cache requires --store-url, --store-db, or JOBHUNTER_DATABASE_URL")
        cache = ProgressiveJobCache(
            store,
            platforms,
            planner=planner,
            fetch_details=args.fetch_details,
            detail_total_limit=args.detail_limit,
            detail_timeout=args.detail_timeout,
        )
        matches = cache.search_or_fetch(
            profile,
            limit=result_limit,
            per_query_limit=args.per_query_limit,
            max_queries=args.max_queries,
        )
        source_errors = cache.errors
        storage_summary = store.save_search_run(
            input_ref=args.input,
            profile=profile,
            sources=_source_names(args.sources, offline=args.offline),
            matches=matches,
            source_errors=source_errors,
            record_jobs=False,
        )
    else:
        agent = JobSearchAgent(platforms, planner=planner, tracer=tracer)
        matches = agent.search(
            profile,
            limit=result_limit,
            per_query_limit=args.per_query_limit,
            max_queries=args.max_queries,
        )
        source_errors = agent.errors
    if args.graph_db:
        graph = KuzuJobGraphStore(args.graph_db)
        graph.project_matches(profile, matches)
        matches = apply_graph_boosts(matches, graph.skill_overlap_boosts(profile))[:result_limit]
    if store_url:
        if storage_summary is None and store is not None:
            storage_summary = store.save_search_run(
                input_ref=args.input,
                profile=profile,
                sources=_source_names(args.sources, offline=args.offline),
                matches=matches,
                source_errors=source_errors,
            )

    output_format = _resolve_output_format(args_json=args.json, show_questions=args.show_questions, preferences=preferences)
    if output_format == "json":
        print(
            json.dumps(
                {
                    "profile": asdict(profile),
                    "adaptive_questions": [asdict(question) for question in questions],
                    "matches": [_match_to_json(match, profile) for match in matches],
                    "source_errors": source_errors,
                    "storage": asdict(storage_summary) if storage_summary else None,
                },
                indent=2,
                default=_json_fallback,
            )
        )
    elif output_format == "tsv":
        _print_tsv(matches, profile)
    else:
        _print_profile(profile)
        if args.show_questions:
            _print_questions(questions)
        _print_errors(source_errors)
        _print_matches(matches)
        if storage_summary:
            _print_storage_summary(storage_summary)
    return 0


def _load_and_update_preferences(path: str | None, assignments: list[str]) -> JobPreferences:
    preferences = load_preferences(path) if path and Path(path).expanduser().exists() else JobPreferences()
    if assignments:
        answers = dict(parse_preference_assignment(assignment) for assignment in assignments)
        preferences = update_preferences(preferences, answers)
        if path:
            save_preferences(path, preferences)
    return preferences


def _resolve_store_url(store_url: str | None, store_db: str | None) -> str | None:
    """Resolve the optional storage URL. Storage stays disabled unless configured.

    Precedence: --store-url, --store-db, JOBHUNTER_DATABASE_URL.
    """

    if store_url and store_db:
        raise SystemExit("use --store-url for remote/production storage or --store-db for local development, not both")
    if store_url:
        return store_url
    if store_db:
        return f"sqlite://{Path(store_db).expanduser().resolve()}"
    return os.environ.get("JOBHUNTER_DATABASE_URL") or None


def _resolve_output_format(*, args_json: bool, show_questions: bool, preferences: JobPreferences) -> str:
    if args_json:
        return "json"
    if show_questions and preferences.output_format is None:
        return "markdown"
    return preferences.output_format or "tsv"


def _build_platforms(value: str) -> list[JobPlatform]:
    platforms: list[JobPlatform] = []
    names = ["hackernews" if part.strip().lower() == "hn" else part.strip().lower() for part in value.split(",") if part.strip()]
    try:
        platforms = build_platforms(names)
    except (ValueError, NotImplementedError) as exc:
        raise SystemExit(str(exc)) from exc
    if not platforms:
        raise SystemExit("no sources selected")
    return platforms


def _source_names(value: str, *, offline: bool) -> tuple[str, ...]:
    if offline:
        return ("offline",)
    return tuple("hackernews" if part.strip().lower() == "hn" else part.strip().lower() for part in value.split(",") if part.strip())


def _print_profile(profile) -> None:
    print("Profile")
    print(f"  name: {profile.name or '-'}")
    print(f"  headline: {profile.headline or '-'}")
    print(f"  roles: {', '.join(profile.roles) or '-'}")
    print(f"  skills: {', '.join(profile.skills[:10]) or '-'}")
    print(f"  locations: {', '.join(profile.locations) or '-'}")
    if any(asdict(profile.preferences).values()):
        print(f"  preferences: {asdict(profile.preferences)}")
    print()


def _print_questions(questions) -> None:
    print("Adaptive questions")
    if not questions:
        print("  No missing preference questions.")
        print()
        return
    for question in questions:
        examples = f" Examples: {', '.join(question.examples)}" if question.examples else ""
        print(f"  {question.id}: {question.prompt} ({question.reason}){examples}")
    print()


def _print_matches(matches) -> None:
    print("Ranked jobs")
    if not matches:
        print("  No matches found.")
        return
    for index, match in enumerate(matches, start=1):
        job = match.job
        print(f"{index}. [{match.score:>5}] {job.title} - {job.company} ({job.source})")
        print(f"   {job.location or 'Location not listed'} | {job.salary or 'Salary not listed'}")
        print(f"   {match.rationale}")
        print(f"   {job.url}")


def _print_tsv(matches, profile) -> None:
    writer = (
        "rank\tscore\ttitle\tcompany\tsource\tlocation\tsalary\turl\tapply_url\tmatched_terms\trationale\toutreach_message"
    )
    print(writer)
    for index, match in enumerate(matches, start=1):
        job = match.job
        values = (
            str(index),
            str(match.score),
            job.title,
            job.company,
            job.source,
            job.location or "",
            job.salary or "",
            job.url,
            resolve_apply_url(match),
            ", ".join(match.matched_terms),
            match.rationale,
            build_outreach_message(profile, match),
        )
        print("\t".join(_tsv_cell(value) for value in values))


def _tsv_cell(value: str) -> str:
    return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()


def _print_storage_summary(summary) -> None:
    print()
    print("Storage")
    print(f"  run_id: {summary.run_id}")
    print(f"  jobs_seen: {summary.jobs_seen}")
    print(f"  jobs_inserted: {summary.jobs_inserted}")
    print(f"  jobs_updated: {summary.jobs_updated}")
    print(f"  matches_inserted: {summary.matches_inserted}")


def _print_errors(errors) -> None:
    if not errors:
        return
    print("Source warnings")
    for error in errors[:5]:
        print(f"  {error}")
    if len(errors) > 5:
        print(f"  ... {len(errors) - 5} more")
    print()


def _match_to_json(match, profile) -> dict[str, Any]:
    data = asdict(match)
    posted_at = data["job"].get("posted_at")
    if isinstance(posted_at, datetime):
        data["job"]["posted_at"] = posted_at.isoformat()
    data["apply_url"] = resolve_apply_url(match)
    data["outreach_message"] = build_outreach_message(profile, match)
    return data


def _json_fallback(value: Any) -> str:
    # Source adapters keep raw payloads that can hold dates, Decimals, or
    # other non-JSON types (e.g. JobSpy date_posted is a datetime.date).
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


if __name__ == "__main__":
    raise SystemExit(main())
