import tempfile
from pathlib import Path

from jobhunter.graph import KuzuJobGraphStore, apply_graph_boosts
from jobhunter.models import JobMatch, JobPosting, JobPreferences, SearchQuery
from jobhunter.profile import build_user_profile


def test_kuzu_graph_projects_matches_and_returns_skill_boosts_when_available():
    try:
        import kuzu  # noqa: F401
    except ImportError:
        return

    with tempfile.TemporaryDirectory() as tempdir:
        profile = build_user_profile(
            "Machine Learning Engineer with Python LLM agents.",
            preferences=JobPreferences(focus_highlights=("llm agents",)),
        )
        query = SearchQuery(text="machine learning engineer llm", role="machine learning engineer", skills=("llm",))
        match = JobMatch(
            job=JobPosting(
                source="test",
                source_id="1",
                title="Machine Learning Engineer",
                company="Alpha AI",
                url="https://example.com/job",
                description="Build Python LLM agents.",
            ),
            score=10.0,
            matched_terms=("machine learning engineer", "llm", "agents"),
            query=query,
            rationale="Matched llm",
        )
        graph = KuzuJobGraphStore(Path(tempdir) / "jobs.kuzu")

        graph.project_matches(profile, [match])
        boosted = apply_graph_boosts([match], graph.skill_overlap_boosts(profile))

        assert boosted[0].score > match.score
        assert "graph skill overlap" in boosted[0].matched_terms
