import tempfile
from pathlib import Path
from unittest.mock import patch

from jobhunter.cache import ProgressiveJobCache
from jobhunter.models import JobPosting, SearchQuery
from jobhunter.profile import build_user_profile
from jobhunter.storage import SQLiteJobStore


class CountingPlatform:
    name = "test-source"

    def __init__(self):
        self.calls = 0

    def search(self, query, profile, *, limit=20):
        self.calls += 1
        return [
            JobPosting(
                source=self.name,
                source_id=f"job-{self.calls}",
                title="Machine Learning Engineer",
                company="Alpha AI",
                url=f"https://jobs.example.com/{self.calls}",
                location="Remote US",
                description="Build Python LLM infrastructure and machine learning systems.",
            )
        ]


def test_progressive_cache_reuses_fresh_source_query_results():
    with tempfile.TemporaryDirectory() as tempdir:
        store = SQLiteJobStore(Path(tempdir) / "jobs.sqlite")
        platform = CountingPlatform()
        cache = ProgressiveJobCache(store, [platform], max_age_hours=24)
        profile = build_user_profile("Machine Learning Engineer with Python LLM infrastructure. Remote US.")

        first = cache.search_or_fetch(profile, limit=5)
        first_call_count = platform.calls
        second = cache.search_or_fetch(profile, limit=5)

        assert first_call_count >= 1
        assert platform.calls == first_call_count
        assert first
        assert second
        assert second[0].job.title == "Machine Learning Engineer"


def test_progressive_cache_caps_detail_fetches_across_queries():
    class MultiQueryPlanner:
        def plan(self, profile):
            return [
                SearchQuery(text="machine learning engineer python"),
                SearchQuery(text="research engineer llm"),
                SearchQuery(text="software engineer backend"),
            ]

    detail_limits = []

    def fake_enrich(jobs, *, limit=25, timeout=10.0, max_chars=12000):
        detail_limits.append(limit)
        return list(jobs)

    with tempfile.TemporaryDirectory() as tempdir:
        store = SQLiteJobStore(Path(tempdir) / "jobs.sqlite")
        platform = CountingPlatform()
        cache = ProgressiveJobCache(
            store,
            [platform],
            planner=MultiQueryPlanner(),
            fetch_details=True,
            detail_limit_per_fetch=2,
            detail_total_limit=3,
        )
        profile = build_user_profile("Machine Learning Engineer with Python LLM infrastructure. Remote US.")

        with patch("jobhunter.cache.enrich_jobs_with_details", fake_enrich):
            cache.search_or_fetch(profile, limit=5)

        assert detail_limits == [2, 1]


def test_progressive_cache_respects_max_queries():
    class MultiQueryPlanner:
        def plan(self, profile, *, max_queries=8):
            return [
                SearchQuery(text="machine learning engineer python"),
                SearchQuery(text="research engineer llm"),
                SearchQuery(text="software engineer backend"),
            ][:max_queries]

    with tempfile.TemporaryDirectory() as tempdir:
        store = SQLiteJobStore(Path(tempdir) / "jobs.sqlite")
        platform = CountingPlatform()
        cache = ProgressiveJobCache(store, [platform], planner=MultiQueryPlanner())
        profile = build_user_profile("Machine Learning Engineer with Python LLM infrastructure. Remote US.")

        cache.search_or_fetch(profile, limit=5, max_queries=2)

        assert platform.calls == 2
