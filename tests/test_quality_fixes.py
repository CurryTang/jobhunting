from datetime import datetime, timedelta, timezone

from jobhunter.agent import _diversify, _has_core_match, _has_excluded_term, score_job
from jobhunter.models import JobMatch, JobPosting, JobPreferences, SearchQuery
from jobhunter.profile import build_user_profile
from jobhunter.sources.hackernews import _looks_like_job_comment, _strip_html
from jobhunter.sources.jobspy import _clean_record
from jobhunter.storage import _canonical_url


def _match(source: str, score: float, title: str = "Engineer") -> JobMatch:
    job = JobPosting(source=source, source_id=title, title=title, company="Co", url=f"https://example.com/{title}")
    return JobMatch(job=job, score=score)


def test_diversify_reserves_floor_for_minor_sources():
    matches = [_match("loud", 10 - i, title=f"loud{i}") for i in range(10)]
    matches += [_match("quiet", 4.0, title="quiet0"), _match("quiet", 3.5, title="quiet1")]
    matches.sort(key=lambda m: -m.score)

    selected = _diversify(matches, limit=10)

    assert sum(1 for m in selected if m.job.source == "quiet") >= 2
    assert len(selected) == 10


def test_diversify_skips_clearly_weak_floor_candidates():
    matches = [_match("loud", 10 - i, title=f"loud{i}") for i in range(10)]
    matches.append(_match("weak", 0.5, title="weak0"))
    matches.sort(key=lambda m: -m.score)

    selected = _diversify(matches, limit=10)

    assert all(m.job.source != "weak" for m in selected)


def test_core_match_keeps_adjacent_technical_jobs_with_target_roles():
    profile = build_user_profile(
        "Machine Learning Engineer with Python PyTorch LLM systems. Remote.",
        preferences=JobPreferences(target_roles=("machine learning engineer",)),
    )
    job = JobPosting(
        source="yc",
        source_id="1",
        title="Member of Technical Staff",
        company="Lab",
        url="https://example.com/1",
        description="Work on python llm inference and pytorch training systems.",
    )
    match = score_job(job, profile, SearchQuery(text="machine learning engineer"))

    assert _has_core_match(match, profile)


def test_core_match_still_rejects_low_signal_titles_without_target_roles():
    profile = build_user_profile("Machine Learning Engineer with Python PyTorch LLM systems. Remote.")
    job = JobPosting(
        source="jobspy:linkedin",
        source_id="2",
        title="Machine Learning Engineer - AI Trainer",
        company="DataFarm",
        url="https://example.com/2",
        description="Label data and chat with models. python machine learning",
    )
    match = score_job(job, profile, SearchQuery(text="machine learning engineer"))

    assert not _has_core_match(match, profile)


def test_score_job_penalizes_stale_postings():
    profile = build_user_profile("Machine Learning Engineer with Python. Remote.")
    query = SearchQuery(text="machine learning engineer")
    fresh = JobPosting(
        source="remotive",
        source_id="3",
        title="Machine Learning Engineer",
        company="Co",
        url="https://example.com/3",
        description="python machine learning",
        posted_at=datetime.now(timezone.utc) - timedelta(days=2),
    )
    stale = JobPosting(
        source="remotive",
        source_id="4",
        title="Machine Learning Engineer",
        company="Co",
        url="https://example.com/4",
        description="python machine learning",
        posted_at=datetime.now(timezone.utc) - timedelta(days=90),
    )

    assert score_job(stale, profile, query).score < score_job(fresh, profile, query).score
    assert "stale posting" in score_job(stale, profile, query).matched_terms


def test_excluded_terms_use_word_boundaries():
    profile = build_user_profile(
        "Software Engineer with Python Django. Remote.",
        preferences=JobPreferences(excluded_terms=("go",)),
    )
    job = JobPosting(
        source="remotive",
        source_id="5",
        title="Django Engineer",
        company="Co",
        url="https://example.com/5",
        description="Ongoing django work",
    )

    assert not _has_excluded_term(job, profile)


def test_hackernews_rejects_job_seeker_comments():
    assert not _looks_like_job_comment("I'm AI Engineer hands on with agents, looking for a role. Remote.")
    assert _looks_like_job_comment("Acme | Senior ML Engineer | Remote (US) | Full-time\nWe are hiring engineers.")


def test_hackernews_strip_html_preserves_first_line():
    text = _strip_html("Acme | ML Engineer | Remote<p>We build systems.</p><p>Apply now.</p>")
    assert text.split("\n")[0] == "Acme | ML Engineer | Remote"


def test_jobspy_clean_record_replaces_nan_with_none():
    nan = float("nan")
    cleaned = _clean_record({"title": "ML Engineer", "company": nan, "min_amount": nan})
    assert cleaned["company"] is None
    assert cleaned["min_amount"] is None
    assert cleaned["title"] == "ML Engineer"


def test_canonical_url_sorts_params_and_strips_tracking():
    first = _canonical_url("https://boards.example.com/jobs?b=2&a=1&ref=linkedin&utm_source=x")
    second = _canonical_url("https://boards.example.com/jobs?a=1&b=2&trk=feed")
    assert first == second
    third = _canonical_url("https://boards.example.com/jobs?gh_jid=123")
    fourth = _canonical_url("https://boards.example.com/jobs?gh_jid=456")
    assert third != fourth


def test_remote_region_must_match_remote_us_preference():
    from jobhunter.agent import has_location_mismatch

    profile = build_user_profile(
        "Machine Learning Engineer with Python. United States.",
        preferences=JobPreferences(preferred_locations=("Remote US", "United States"), remote=True),
    )

    def job_at(location):
        return JobPosting(source="lever", source_id=location, title="ML Engineer", company="Co", url="https://example.com", location=location)

    assert has_location_mismatch(job_at("Remote - Paris"), profile)
    assert not has_location_mismatch(job_at("Remote - United States"), profile)
    assert not has_location_mismatch(job_at("Remote"), profile)
    assert not has_location_mismatch(job_at("Remote Worldwide"), profile)
