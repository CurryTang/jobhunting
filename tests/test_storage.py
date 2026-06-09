import sqlite3
import tempfile
from pathlib import Path

from jobhunter.models import JobMatch, JobPosting, SearchQuery
from jobhunter.profile import build_user_profile
from jobhunter.storage import PostgresJobStore, SQLiteJobStore, create_job_store, job_key


def test_job_key_dedupes_tracking_url_parameters():
    first = JobPosting(
        source="a16z",
        source_id="1",
        title="Researcher",
        company="Alpha",
        url="https://jobs.example.com/opening?utm_source=a16z&x=1",
    )
    second = JobPosting(
        source="yc",
        source_id="2",
        title="Researcher",
        company="Alpha",
        url="https://jobs.example.com/opening?x=1&utm_campaign=test",
    )

    assert job_key(first) == job_key(second)


def test_job_key_dedupes_same_logical_job_across_platforms():
    first = JobPosting(
        source="linkedin",
        source_id="li-1",
        title="Senior Machine Learning Engineer",
        company="OpenAI Inc.",
        url="https://linkedin.example.com/jobs/1",
        location="New York, NY",
    )
    second = JobPosting(
        source="a16z",
        source_id="ats-2",
        title="Machine Learning Engineer",
        company="OpenAI",
        url="https://jobs.ashbyhq.com/openai/example",
        location="New York City, United States",
    )

    assert job_key(first) == job_key(second)


def test_sqlite_store_upserts_jobs_and_records_runs():
    with tempfile.TemporaryDirectory() as tempdir:
        db_path = Path(tempdir) / "jobs.sqlite"
        store = SQLiteJobStore(db_path)
        profile = build_user_profile("Research Scientist with Python LLM. Remote US.")
        query = SearchQuery(text="quant researcher python", role="quant researcher", skills=("python",))
        job = JobPosting(
            source="test",
            source_id="job-1",
            title="Quantitative Researcher",
            company="Alpha Fund",
            url="https://jobs.example.com/alpha?utm_source=test",
            location="New York",
            description="Research alpha signals with Python and market data.",
        )
        match = JobMatch(
            job=job,
            score=12.5,
            matched_terms=("python", "alpha"),
            query=query,
            rationale="Matched python, alpha",
        )

        first = store.save_search_run(input_ref="resume.md", profile=profile, sources=("test",), matches=[match])
        second = store.save_search_run(input_ref="resume.md", profile=profile, sources=("test",), matches=[match])

        assert first.jobs_inserted == 1
        assert first.jobs_updated == 0
        assert second.jobs_inserted == 0
        assert second.jobs_updated == 1

        with sqlite3.connect(db_path) as conn:
            jobs_count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            runs_count = conn.execute("SELECT COUNT(*) FROM search_runs").fetchone()[0]
            matches_count = conn.execute("SELECT COUNT(*) FROM job_matches").fetchone()[0]
            seen_count = conn.execute("SELECT seen_count FROM jobs").fetchone()[0]

        assert jobs_count == 1
        assert runs_count == 2
        assert matches_count == 2
        assert seen_count == 2


def test_sqlite_source_fetch_persists_raw_items_jobs_and_observations():
    with tempfile.TemporaryDirectory() as tempdir:
        db_path = Path(tempdir) / "jobs.sqlite"
        store = SQLiteJobStore(db_path)
        job = JobPosting(
            source="linkedin",
            source_id="job-1",
            title="Machine Learning Engineer",
            company="Alpha AI",
            url="https://linkedin.example.com/jobs/view/1?utm_source=test",
            location="New York",
            description="Build LLM systems in Python.",
            raw={"id": "job-1", "title": "Machine Learning Engineer", "detail_text": "Detailed job page with LLM systems."},
        )

        first = store.save_source_fetch(source="linkedin", query_text="machine learning engineer", jobs=[job])
        second = store.save_source_fetch(source="linkedin", query_text="machine learning engineer", jobs=[job])

        assert first.source_items_inserted == 1
        assert first.jobs_inserted == 1
        assert first.observations_inserted == 1
        assert second.source_items_inserted == 0
        assert second.source_items_updated == 1
        assert second.jobs_inserted == 0
        assert second.jobs_updated == 1

        cached = store.list_cached_jobs(sources=("linkedin",), limit=10)
        assert len(cached) == 1
        assert cached[0].title == "Machine Learning Engineer"
        assert store.has_fresh_source_query("linkedin", "machine learning engineer")

        with sqlite3.connect(db_path) as conn:
            source_items_count = conn.execute("SELECT COUNT(*) FROM source_items").fetchone()[0]
            observations_count = conn.execute("SELECT COUNT(*) FROM job_observations").fetchone()[0]
            fetch_runs_count = conn.execute("SELECT COUNT(*) FROM fetch_runs").fetchone()[0]
            detail_text = conn.execute("SELECT detail_text FROM source_items").fetchone()[0]

        assert source_items_count == 1
        assert observations_count == 2
        assert fetch_runs_count == 2
        assert "Detailed job page" in detail_text


def test_failed_source_fetch_is_recorded_but_not_marked_fresh():
    with tempfile.TemporaryDirectory() as tempdir:
        store = SQLiteJobStore(Path(tempdir) / "jobs.sqlite")

        summary = store.save_source_fetch(
            source="linkedin",
            query_text="quant researcher",
            jobs=[],
            status="error",
            error="rate limited",
        )

        assert summary.jobs_seen == 0
        assert store.has_fresh_source_query("linkedin", "quant researcher") is False


def test_create_job_store_uses_postgres_for_remote_database_urls():
    store = create_job_store("postgresql://user:pass@db.example.com:5432/jobhunter")

    assert isinstance(store, PostgresJobStore)


def test_create_job_store_supports_sqlite_only_for_development_urls():
    with tempfile.TemporaryDirectory() as tempdir:
        db_path = Path(tempdir) / "jobs.sqlite"
        store = create_job_store(f"sqlite:///{db_path}")

        assert isinstance(store, SQLiteJobStore)


def test_create_job_store_rejects_unknown_database_schemes():
    try:
        create_job_store("file:///tmp/jobs.db")
    except ValueError as exc:
        assert "unsupported store URL scheme" in str(exc)
    else:
        raise AssertionError("expected unsupported scheme to fail")
