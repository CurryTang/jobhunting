import json

import pytest

from jobhunter.models import JobMatch, JobPosting, SearchQuery
from jobhunter.outreach import build_outreach_message, resolve_apply_url
from jobhunter.profile import build_user_profile
from jobhunter.sources.companies import CompanyBoardsPlatform, _parse_google_jobs

QUERY = SearchQuery(text="machine learning engineer python", role="machine learning engineer", skills=("python",))
PROFILE = build_user_profile("Zhikai Chen\nMachine Learning Engineer with Python LLM. https://github.com/CurryTang United States.")


def test_companies_amazon_provider_normalizes(monkeypatch):
    payload = {
        "jobs": [
            {
                "id": "abc",
                "id_icims": "123",
                "title": "Machine Learning Engineer",
                "company_name": "Amazon Web Services, Inc.",
                "job_path": "/en/jobs/123/machine-learning-engineer",
                "url_next_step": "https://account.amazon.com/jobs/123/apply",
                "normalized_location": "Arlington, Virginia, USA",
                "description": "Build ML systems with <b>python</b>.",
                "basic_qualifications": "3+ years python",
                "posted_date": "June 1, 2026",
                "job_category": "Applied Science",
            }
        ]
    }
    monkeypatch.setattr("jobhunter.sources.companies.fetch_json", lambda url, **kwargs: payload)

    platform = CompanyBoardsPlatform(companies=("amazon",))
    jobs = platform.search(QUERY, PROFILE, limit=5)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "company:amazon"
    assert job.url == "https://www.amazon.jobs/en/jobs/123/machine-learning-engineer"
    assert job.raw["url_next_step"] == "https://account.amazon.com/jobs/123/apply"
    assert job.posted_at is not None


def test_companies_unsupported_entry_warns_and_skips():
    with pytest.warns(UserWarning, match="GraphQL"):
        platform = CompanyBoardsPlatform(companies=("meta", "amazon"))
    assert platform._supported == ["amazon"]


def test_companies_unknown_entry_collected_as_error(monkeypatch):
    platform = CompanyBoardsPlatform(companies=("nonsense",))
    jobs = platform.search(QUERY, PROFILE, limit=5)
    assert jobs == []
    assert platform.company_errors and "nonsense" in platform.company_errors[0]


def test_parse_google_jobs_extracts_entries():
    entry = [
        "99351668776149702",
        "Machine Learning Software Engineer",
        "https://www.google.com/about/careers/applications/signin?jobId=x",
        [None, "<ul><li>Build python ML models</li></ul>"],
        [None, "<h3>Minimum qualifications</h3>"],
        "projects/x",
        None,
        "Google",
        "en-US",
        [["Mountain View, CA, USA", ["addr"], "Mountain View", "94043", "CA", "US"]],
        [None, "<p>Google engineers...</p>"],
        [2, 3, 4],
        [1778841122, 947000000],
    ]
    html = (
        "AF_initDataCallback({key: 'ds:1', hash: '2', data:"
        + json.dumps([[entry]])
        + ", sideChannel: {}});"
    )

    jobs = _parse_google_jobs(html)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "company:google"
    assert job.company == "Google"
    assert job.location == "Mountain View, CA, USA"
    assert job.raw["apply_url"].startswith("https://www.google.com/about/careers/applications/signin")
    assert job.posted_at is not None and job.posted_at.year == 2026


def _match_for(raw: dict, **job_kwargs) -> JobMatch:
    job = JobPosting(
        source=job_kwargs.pop("source", "company:amazon"),
        source_id="1",
        title=job_kwargs.pop("title", "Machine Learning Engineer"),
        company=job_kwargs.pop("company", "Amazon"),
        url=job_kwargs.pop("url", "https://www.amazon.jobs/en/jobs/1/x"),
        raw=raw,
        **job_kwargs,
    )
    return JobMatch(job=job, score=5.0, matched_terms=("machine learning", "python", "remote preferred"))


def test_resolve_apply_url_prefers_raw_apply_link():
    match = _match_for({"url_next_step": "https://account.amazon.com/jobs/1/apply"})
    assert resolve_apply_url(match) == "https://account.amazon.com/jobs/1/apply"
    assert resolve_apply_url(_match_for({})) == "https://www.amazon.jobs/en/jobs/1/x"


def test_outreach_message_mentions_skills_company_and_link():
    message = build_outreach_message(PROFILE, _match_for({}))
    assert message.startswith("Hi Amazon team, I'm Zhikai Chen")
    assert "machine learning" in message and "python" in message
    assert "remote preferred" not in message
    assert "https://github.com/CurryTang" in message
    assert "Machine Learning Engineer" in message
    assert "\n" not in message
