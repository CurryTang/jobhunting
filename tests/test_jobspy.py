import sys
import types

import pytest

from jobhunter.models import SearchQuery
from jobhunter.profile import build_user_profile
from jobhunter.sources.jobspy import LinkedInJobSpyPlatform


class FakeDataFrame:
    def __init__(self, records):
        self.records = records

    def to_dict(self, orient):
        assert orient == "records"
        return self.records


def test_linkedin_jobspy_platform_normalizes_records(monkeypatch):
    calls = []

    def scrape_jobs(**kwargs):
        calls.append(kwargs)
        return FakeDataFrame(
            [
                {
                    "id": "123",
                    "title": "Machine Learning Engineer",
                    "company": "Acme AI",
                    "job_url": "https://www.linkedin.com/jobs/view/123",
                    "location": {"city": "San Francisco", "state": "CA", "country": "USA"},
                    "description": "Python LLM systems.",
                    "job_type": "fulltime",
                    "min_amount": 150000,
                    "max_amount": 200000,
                    "interval": "yearly",
                    "currency": "$",
                    "date_posted": "2026-06-01",
                }
            ]
        )

    fake_module = types.SimpleNamespace(scrape_jobs=scrape_jobs)
    monkeypatch.setitem(sys.modules, "jobspy", fake_module)

    profile = build_user_profile("Machine Learning Engineer with Python LLM. United States.")
    query = SearchQuery(
        text="machine learning engineer python llm",
        role="machine learning engineer",
        skills=("python", "llm"),
        location="united states",
        remote=True,
    )

    jobs = LinkedInJobSpyPlatform(results_wanted=5).search(query, profile, limit=3)

    assert calls[0]["site_name"] == ["linkedin"]
    assert calls[0]["search_term"] == "machine learning engineer python llm"
    assert calls[0]["location"] == "United States"
    assert calls[0]["results_wanted"] == 3
    assert jobs[0].source == "jobspy:linkedin"
    assert jobs[0].title == "Machine Learning Engineer"
    assert jobs[0].company == "Acme AI"
    assert jobs[0].location == "San Francisco, CA, USA"
    assert jobs[0].salary == "$150000-$200000 yearly"


def test_linkedin_jobspy_platform_reports_missing_dependency(monkeypatch):
    # Setting the module entry to None forces `import jobspy` to raise
    # ImportError even when python-jobspy is installed in the environment.
    monkeypatch.setitem(sys.modules, "jobspy", None)

    with pytest.raises(RuntimeError, match="python-jobspy"):
        LinkedInJobSpyPlatform().search(SearchQuery(text="python"), build_user_profile("Python"))
