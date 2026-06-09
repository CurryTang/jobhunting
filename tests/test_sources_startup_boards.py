import json
from io import BytesIO

from jobhunter.models import SearchQuery
from jobhunter.profile import build_user_profile
from jobhunter.sources.a16z import A16ZPlatform
from jobhunter.sources.yc import YCJobsPlatform


class FakeResponse:
    def __init__(self, body, content_type="application/json"):
        self.body = body.encode("utf-8")
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def test_a16z_platform_normalizes_public_api_response(monkeypatch):
    payload = {
        "jobs": [
            {
                "jobId": "a1",
                "title": "AI Engineer",
                "companyName": "Future AI",
                "applyUrl": "https://example.com/apply",
                "locations": ["Remote - United States"],
                "jobTypes": [{"label": "AI Engineer"}],
                "jobFunctions": [{"label": "Engineering"}],
                "markets": [{"label": "AI"}],
                "skills": ["Python", "LLM"],
                "salary": {
                    "minValue": 150000,
                    "maxValue": 210000,
                    "currency": {"label": "USD"},
                    "period": {"label": "Year"},
                },
            }
        ]
    }

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://jobs.a16z.com/api-boards/search-jobs"
        return FakeResponse(json.dumps(payload))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    jobs = A16ZPlatform().search(SearchQuery(text="python llm"), build_user_profile("Python LLM"), limit=1)

    assert jobs[0].source == "a16z"
    assert jobs[0].title == "AI Engineer"
    assert jobs[0].company == "Future AI"
    assert jobs[0].location == "Remote - United States"
    assert jobs[0].salary == "USD 150000-210000 / Year"
    assert "LLM" in jobs[0].tags


def test_yc_platform_extracts_embedded_jobs(monkeypatch):
    page = {
        "props": {
            "jobPostings": [
                {
                    "id": 1,
                    "title": "AI / ML Engineer",
                    "url": "/companies/acme/jobs/1-ai-ml-engineer",
                    "location": "Remote (US)",
                    "type": "Full-time",
                    "prettyRole": "Engineering",
                    "roleSpecificType": "Machine learning",
                    "skills": ["Python"],
                    "salaryRange": "$130K - $180K",
                    "companyName": "Acme",
                    "companyOneLiner": "AI-native tools",
                }
            ]
        }
    }
    html = '<div data-page="' + json.dumps(page).replace('"', "&quot;") + '"></div>'

    def fake_urlopen(request, timeout):
        return FakeResponse(html, content_type="text/html")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    jobs = YCJobsPlatform().search(SearchQuery(text="python"), build_user_profile("Python"), limit=1)

    assert jobs[0].source == "yc"
    assert jobs[0].title == "AI / ML Engineer"
    assert jobs[0].company == "Acme"
    assert jobs[0].url == "https://www.ycombinator.com/companies/acme/jobs/1-ai-ml-engineer"
