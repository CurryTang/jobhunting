from jobhunter.models import SearchQuery
from jobhunter.profile import build_user_profile
from jobhunter.sources.greenhouse import GreenhousePlatform
from jobhunter.sources.lever import LeverPlatform
from jobhunter.sources.remoteok import RemoteOKPlatform

QUERY = SearchQuery(text="machine learning engineer python", role="machine learning engineer", skills=("python",))
PROFILE = build_user_profile("Machine Learning Engineer with Python. Remote.")


def test_remoteok_normalizes_and_filters(monkeypatch):
    payload = [
        {"last_updated": 1, "legal": "notice"},
        {
            "id": "42",
            "position": "Machine Learning Engineer",
            "company": "Acme &amp; Co",
            "tags": ["python", "ml"],
            "location": "Worldwide",
            "date": "2026-06-08T21:54:18+00:00",
            "salary_min": 150000,
            "salary_max": 200000,
            "url": "https://remoteok.com/remote-jobs/42",
            "description": "<p>Train LLMs with python.</p>",
        },
        {
            "id": "43",
            "position": "Account Executive",
            "company": "SalesCo",
            "tags": ["sales"],
            "location": "Worldwide",
            "date": "2026-06-08T21:54:18+00:00",
            "url": "https://remoteok.com/remote-jobs/43",
            "description": "Sell things.",
        },
    ]
    monkeypatch.setattr("jobhunter.sources.remoteok.fetch_json", lambda url, **kwargs: payload)

    jobs = RemoteOKPlatform().search(QUERY, PROFILE, limit=10)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.title == "Machine Learning Engineer"
    assert job.company == "Acme & Co"
    assert job.salary == "$150000-$200000 yearly"
    assert job.posted_at is not None
    assert "Train LLMs" in job.description


def test_greenhouse_fetches_each_board_once_and_skips_404(monkeypatch):
    import urllib.error

    calls = []

    def fake_fetch(url, **kwargs):
        calls.append(url)
        if "deadco" in url:
            raise urllib.error.HTTPError(url, 404, "gone", None, None)
        return {
            "jobs": [
                {
                    "id": 7,
                    "title": "Research Engineer, Machine Learning",
                    "updated_at": "2026-06-05T10:00:00-04:00",
                    "first_published": "2026-05-20T10:00:00-04:00",
                    "absolute_url": "https://boards.greenhouse.io/anthropic/jobs/7",
                    "location": {"name": "San Francisco, CA"},
                    "content": "Build with &lt;b&gt;python&lt;/b&gt; and LLMs.",
                    "departments": [{"name": "Research"}],
                }
            ]
        }

    monkeypatch.setattr("jobhunter.sources.greenhouse.fetch_json", fake_fetch)
    platform = GreenhousePlatform(boards=("anthropic", "deadco"))

    jobs = platform.search(QUERY, PROFILE, limit=10)
    platform.search(QUERY, PROFILE, limit=10)

    assert len(calls) == 2  # one per board, cached afterwards
    assert len(jobs) == 1
    assert jobs[0].company == "Anthropic"
    assert jobs[0].posted_at is not None
    assert "python" in jobs[0].description


def test_ashby_normalizes_and_filters(monkeypatch):
    from jobhunter.sources.ashby import AshbyPlatform

    payload = {
        "jobs": [
            {
                "id": "a1",
                "title": "Research Engineer, Machine Learning",
                "descriptionPlain": "Build LLM systems with python.",
                "location": "San Francisco",
                "isRemote": True,
                "isListed": True,
                "department": "Research",
                "employmentType": "FullTime",
                "publishedAt": "2026-03-12T16:38:15.322+00:00",
                "jobUrl": "https://jobs.ashbyhq.com/openai/a1",
                "applyUrl": "https://jobs.ashbyhq.com/openai/a1/application",
            },
            {
                "id": "a2",
                "title": "Office Manager",
                "descriptionPlain": "Run the office.",
                "location": "San Francisco",
                "isListed": True,
            },
        ]
    }
    monkeypatch.setattr("jobhunter.sources.ashby.fetch_json", lambda url, **kwargs: payload)

    jobs = AshbyPlatform(slugs=("openai",)).search(QUERY, PROFILE, limit=10)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.source == "company:openai"
    assert job.company == "Openai"
    assert job.location == "Remote - San Francisco"
    assert job.raw["applyUrl"].endswith("/application")
    assert job.posted_at is not None


def test_lever_normalizes_postings(monkeypatch):
    payload = [
        {
            "id": "abc",
            "text": "Machine Learning Engineer",
            "hostedUrl": "https://jobs.lever.co/mistral/abc",
            "categories": {"team": "Research", "location": "Paris", "commitment": "Full-time"},
            "workplaceType": "remote",
            "createdAt": 1780000000000,
            "descriptionPlain": "Work on python LLM training.",
        }
    ]
    monkeypatch.setattr("jobhunter.sources.lever.fetch_json", lambda url, **kwargs: payload)

    jobs = LeverPlatform(companies=("mistral",)).search(QUERY, PROFILE, limit=10)

    assert len(jobs) == 1
    job = jobs[0]
    assert job.company == "Mistral AI"
    assert job.location == "Remote - Paris"
    assert job.posted_at is not None
    assert "Research" in job.tags
