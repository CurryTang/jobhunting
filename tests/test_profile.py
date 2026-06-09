import base64

from jobhunter import profile as profile_module
from jobhunter.profile import build_user_profile, load_input


def test_build_user_profile_extracts_core_fields():
    raw = """# Ada Chen
Machine Learning Engineer
Python, PyTorch, SQL, Kubernetes
Remote United States
"""

    profile = build_user_profile(raw)

    assert profile.name == "Ada Chen"
    assert "machine learning engineer" in profile.roles
    assert "python" in profile.skills
    assert "pytorch" in profile.skills
    assert "remote" in profile.locations
    assert profile.headline == "Machine Learning Engineer"


def test_load_input_returns_raw_text_when_not_file_or_url():
    assert load_input("Python backend engineer") == "Python backend engineer"


def test_github_profile_input_includes_public_repo_metadata(monkeypatch):
    def fake_github_get_json(url, *, timeout):
        if url.endswith("/repos/CurryTang/CurryTang/readme"):
            content = """### Hi there
I'm currently a CS PhD student at Michigan State University.

## Research & Projects

### 1. DL Infra, Agent, Long Context Modeling (2026-present)
Currently working on new directions.

Projects:
* Amadeus: AI-powered research assistant for paper discovery, reading, and analysis
* Slack GPU Monitor: A slack bot to manage your server's GPU.

### 3. Graph Foundation Models and Large Language Models (2023-2025)
Note: In the past, I worked on graph foundation models for a while, these related libraries won't be maintained any more.
"""
            return {"content": base64.b64encode(content.encode("utf-8")).decode("ascii")}
        if url.endswith("/users/CurryTang"):
            return {
                "name": "Zhikai Chen",
                "bio": None,
                "company": "Michigan State University",
                "location": "East Lansing",
                "blog": "",
                "html_url": "https://github.com/CurryTang",
            }
        return [
            {
                "name": "Graph-LLM",
                "fork": False,
                "language": "Python",
                "description": "Exploring Large Language Models in Learning on Graphs",
                "topics": ["llm", "graphs"],
                "pushed_at": "2025-03-10T05:30:05Z",
                "updated_at": "2026-05-26T07:43:10Z",
            }
        ]

    monkeypatch.setattr(profile_module, "_github_get_json", fake_github_get_json)

    raw = load_input("https://github.com/CurryTang")
    profile = build_user_profile(raw)

    assert "GitHub profile self-introduction" in raw
    assert "DL Infra, Agent, Long Context Modeling" in raw
    assert "won't be maintained any more" in raw
    assert "Graph-LLM" in raw
    assert "python" in profile.skills
    assert "llm" in profile.skills
    assert "graphs" in profile.skills
    assert "dl infra" in profile.skills
    assert "long context" in profile.skills
    assert "gpu" in profile.skills
    assert "east lansing" in profile.locations
    assert "united states" in profile.locations
    assert "research scientist" in profile.roles
    assert "machine learning engineer" in profile.roles
    assert "research engineer" in profile.roles


def test_profile_highlights_prioritize_current_work_over_deprecated_sections():
    raw = """# Riley Doe
Research Scientist

## Current Work (2026-present)
* Built an agentic memory system for long-context modeling and forecasting.
* Published an arXiv preprint on proactive agents and evaluation.

## Past Graph Projects (2021-2022)
Note: these graph libraries are deprecated and will not be maintained.
* Old graph benchmark with many stale datasets.
"""

    profile = build_user_profile(raw)
    highlights = profile.evidence["portfolio_highlights"]
    highlight_text = "\n".join(str(item["text"]) for item in highlights)

    assert highlights
    assert any("agentic memory system" in str(item["text"]) for item in highlights[:2])
    assert "proactive agents" in highlight_text
    assert "Old graph benchmark" not in highlight_text
    assert "agentic" in profile.skills
    assert "long context" in profile.skills
