from jobhunter.agent import AgenticQueryPlanner, JobSearchAgent, QueryPlanner, _has_core_match, has_location_mismatch, score_job
from jobhunter.models import JobPosting, JobPreferences, SearchQuery
from jobhunter.profile import build_user_profile
from jobhunter.sources.offline import OfflineDemoPlatform


def test_query_planner_uses_profile_role_and_skills():
    profile = build_user_profile("Machine Learning Engineer with Python PyTorch SQL. Remote.")

    queries = QueryPlanner().plan(profile)

    assert queries
    assert queries[0].role == "machine learning engineer"
    assert "python" in queries[0].skills


def test_query_planner_adds_compact_skill_pair_queries():
    profile = build_user_profile("Graph LLM Python research systems.")

    query_texts = [query.text for query in QueryPlanner().plan(profile)]

    assert "python llm" in query_texts
    assert "graph llm" in query_texts


def test_query_planner_avoids_generic_keyword_queries_when_roles_are_explicit():
    profile = build_user_profile(
        "LLM post-training agents relational deep learning exploring focus llms.",
        preferences=JobPreferences(target_roles=("machine learning engineer", "software engineer")),
    )

    query_texts = [query.text for query in QueryPlanner().plan(profile, max_queries=10)]

    assert "llm post-training agents relational deep learning" not in query_texts
    assert "exploring focus llms" not in " ".join(query_texts)
    assert query_texts[0].startswith("machine learning engineer")


def test_query_planner_expands_quant_preferences():
    profile = build_user_profile(
        "Graph LLM Python research systems.",
        preferences=JobPreferences(
            target_roles=("quantitative researcher",),
            industries=("quant finance",),
            preferred_locations=("New York",),
        ),
    )

    query_texts = [query.text for query in QueryPlanner().plan(profile)]

    assert "quantitative researcher machine learning python" in query_texts
    assert "quant research engineer python machine learning" in query_texts
    assert query_texts[0].startswith("quantitative researcher")


def test_query_planner_prioritizes_user_selected_focus_highlights():
    profile = build_user_profile(
        "Research Scientist with Python LLM graph systems and agentic memory.",
        preferences=JobPreferences(focus_highlights=("agentic memory long context evaluation",)),
    )

    queries = QueryPlanner().plan(profile)

    assert "agentic memory" in queries[0].text


def test_agentic_query_planner_expands_mle_sde_and_quant_tracks_for_broad_search():
    profile = build_user_profile(
        "Python LLM systems researcher.",
        preferences=JobPreferences(
            target_roles=("machine learning engineer", "software engineer", "quantitative researcher"),
            industries=("quant", "AI"),
            result_count=150,
        ),
    )

    texts = [query.text for query in AgenticQueryPlanner().plan(profile, max_queries=30)]

    assert "machine learning engineer python" in texts
    assert "software engineer python backend" in texts
    assert "quantitative researcher machine learning" in texts


def test_score_job_prefers_matching_terms():
    profile = build_user_profile("Machine Learning Engineer with Python PyTorch. Remote.")
    query = SearchQuery(text="machine learning engineer python", role="machine learning engineer", skills=("python",))
    job = JobPosting(
        source="test",
        source_id="1",
        title="Machine Learning Engineer",
        company="Acme",
        url="https://example.com",
        location="Remote",
        description="Python and PyTorch role.",
    )

    match = score_job(job, profile, query)

    assert match.score > 5
    assert "machine learning engineer" in match.matched_terms
    assert "python" in match.matched_terms


def test_quant_preference_ranks_quant_role_above_generic_llm_role():
    class MixedPlatform:
        name = "mixed"

        def search(self, query, profile, *, limit=20):
            return [
                JobPosting(
                    source=self.name,
                    source_id="generic-llm",
                    title="Applied AI Engineer",
                    company="Generic AI",
                    url="https://example.com/generic",
                    location="Remote US",
                    description="Build LLM agents in Python for enterprise workflows.",
                ),
                JobPosting(
                    source=self.name,
                    source_id="quant-ml",
                    title="Quantitative Researcher - Machine Learning",
                    company="Alpha Fund",
                    url="https://example.com/quant",
                    location="New York",
                    description="Research alpha signals with Python, machine learning, graph models, and market data.",
                ),
            ]

    profile = build_user_profile(
        "Graph LLM Python research systems.",
        preferences=JobPreferences(
            target_roles=("quantitative researcher", "machine learning researcher"),
            preferred_locations=("New York", "Remote US"),
            industries=("quant finance", "AI"),
            remote=True,
        ),
    )

    matches = JobSearchAgent([MixedPlatform()]).search(profile, limit=2)

    assert [match.job.source_id for match in matches] == ["quant-ml"]
    assert "quant finance evidence" in matches[0].matched_terms


def test_quant_search_rejects_soft_finance_word_noise():
    class NoisyPlatform:
        name = "noisy"

        def search(self, query, profile, *, limit=20):
            return [
                JobPosting(
                    source=self.name,
                    source_id="editor",
                    title="AI Cinematic Video Editor",
                    company="Market Options Studio",
                    url="https://example.com/editor",
                    location="Remote",
                    description="Use AI tools for creative video editing and portfolio marketing.",
                ),
                JobPosting(
                    source=self.name,
                    source_id="quant",
                    title="Quantitative Researcher - Machine Learning",
                    company="Alpha Fund",
                    url="https://example.com/quant",
                    location="New York",
                    description="Research alpha signals with Python and machine learning for systematic trading.",
                ),
            ]

    profile = build_user_profile(
        "LLM Python machine learning researcher.",
        preferences=JobPreferences(
            target_roles=("quantitative researcher", "machine learning engineer", "software engineer"),
            industries=("quant", "AI", "startup"),
            preferred_locations=("New York", "Remote US"),
            remote=True,
        ),
    )

    matches = JobSearchAgent([NoisyPlatform()]).search(profile, limit=5)

    assert [match.job.source_id for match in matches] == ["quant"]
    assert "quant finance evidence" in matches[0].matched_terms


def test_technical_search_rejects_low_signal_trainer_titles():
    class TrainerPlatform:
        name = "trainer"

        def search(self, query, profile, *, limit=20):
            return [
                JobPosting(
                    source=self.name,
                    source_id="trainer",
                    title="Machine Learning Engineer - AI Trainer",
                    company="DataAnnotation",
                    url="https://example.com/trainer",
                    location="New York",
                    description="Train AI systems through annotation tasks.",
                ),
                JobPosting(
                    source=self.name,
                    source_id="mle",
                    title="Machine Learning Engineer",
                    company="Scale AI",
                    url="https://example.com/mle",
                    location="New York",
                    description="Build machine learning systems with Python and LLMs.",
                ),
            ]

    profile = build_user_profile(
        "Python LLM machine learning researcher.",
        preferences=JobPreferences(
            target_roles=("machine learning engineer", "research scientist"),
            preferred_locations=("New York",),
        ),
    )

    matches = JobSearchAgent([TrainerPlatform()]).search(profile, limit=5)

    assert [match.job.source_id for match in matches] == ["mle"]


def test_role_aliases_score_machine_learning_researcher():
    profile = build_user_profile(
        "Python LLM machine learning researcher.",
        preferences=JobPreferences(target_roles=("research scientist", "machine learning engineer")),
    )
    query = SearchQuery(text="research scientist machine learning", role="research scientist", skills=("machine learning",))
    job = JobPosting(
        source="test",
        source_id="ml-researcher",
        title="Machine Learning Researcher",
        company="Alpha Lab",
        url="https://example.com",
        location="New York",
        description="Research machine learning models with Python.",
    )

    match = score_job(job, profile, query)

    assert "machine learning researcher" in match.matched_terms
    assert _has_core_match(match, profile) is True


def test_industry_matching_uses_word_boundaries():
    profile = build_user_profile(
        "Python machine learning engineer.",
        preferences=JobPreferences(target_roles=("software engineer",), industries=("AI",)),
    )
    query = SearchQuery(text="software engineer python", role="software engineer", skills=("python",))
    job = JobPosting(
        source="test",
        source_id="prairie",
        title="Software Engineer",
        company="PrairieLearn",
        url="https://example.com",
        location="Remote",
        description="Build education infrastructure with Python.",
    )

    match = score_job(job, profile, query)

    assert "AI" not in match.matched_terms


def test_intern_seniority_is_not_scored_for_full_time_search():
    profile = build_user_profile(
        "Machine Learning Engineer with Python. Previously a research intern.",
        preferences=JobPreferences(target_roles=("software engineer",)),
    )
    query = SearchQuery(text="software engineer python", role="software engineer", skills=("python",))
    job = JobPosting(
        source="test",
        source_id="fulltime",
        title="Software Engineer",
        company="Internal Systems",
        url="https://example.com",
        location="Remote",
        description="Build internal platforms with Python.",
    )

    match = score_job(job, profile, query)

    assert "intern" not in match.matched_terms


def test_location_matching_accepts_named_city_with_remote_us_preference():
    profile = build_user_profile(
        "Python LLM researcher.",
        preferences=JobPreferences(preferred_locations=("New York", "Remote US"), remote=True),
    )
    job = JobPosting(
        source="test",
        source_id="nyc",
        title="Quantitative Researcher",
        company="Alpha Fund",
        url="https://example.com",
        location="New York",
    )

    assert has_location_mismatch(job, profile) is False


def test_agent_returns_ranked_offline_matches():
    profile = build_user_profile("Machine Learning Engineer with Python PyTorch LLM. Remote.")

    matches = JobSearchAgent([OfflineDemoPlatform()]).search(profile, limit=2)

    assert len(matches) == 2
    assert matches[0].score >= matches[1].score
    assert matches[0].job.company == "Vector Labs"


def test_agent_filters_research_only_nontechnical_matches():
    class ResearchOnlyPlatform:
        name = "research-only"

        def search(self, query, profile, *, limit=20):
            return [
                JobPosting(
                    source=self.name,
                    source_id="copywriter",
                    title="Copywriter",
                    company="Words Inc",
                    url="https://example.com/copywriter",
                    location="Worldwide",
                    description="Academic research and writing role.",
                )
            ]

    profile = build_user_profile("Research Engineer with Python LLM graph systems. United States.")

    matches = JobSearchAgent([ResearchOnlyPlatform()]).search(profile)

    assert matches == []


def test_agent_records_source_errors():
    class BrokenPlatform:
        name = "broken"

        def search(self, query, profile, *, limit=20):
            raise RuntimeError("missing dependency")

    agent = JobSearchAgent([BrokenPlatform()])
    matches = agent.search(build_user_profile("Python LLM engineer"))

    assert matches == []
    assert "missing dependency" in agent.errors[0]
