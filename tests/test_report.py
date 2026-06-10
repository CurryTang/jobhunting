from html.parser import HTMLParser

from jobhunter.models import JobMatch, JobPosting
from jobhunter.profile import build_user_profile
from jobhunter.report import render_html


class _Validator(HTMLParser):
    def error(self, message):  # pragma: no cover - only fires on malformed HTML
        raise ValueError(message)


def _profile():
    return build_user_profile("Zhikai Chen. Machine Learning Engineer with Python LLM. https://github.com/CurryTang")


def _match(**overrides):
    job = JobPosting(
        source=overrides.pop("source", "company:amazon"),
        source_id="1",
        title=overrides.pop("title", "Machine Learning Engineer"),
        company=overrides.pop("company", "Amazon"),
        url=overrides.pop("url", "https://www.amazon.jobs/jobs/1"),
        location=overrides.pop("location", "Remote US"),
        raw=overrides.pop("raw", {"url_next_step": "https://account.amazon.com/jobs/1/apply"}),
    )
    return JobMatch(job=job, score=12.5, matched_terms=("python", "machine learning"), rationale="Matched python")


def test_render_html_is_well_formed_and_self_contained():
    html = render_html(_profile(), [_match()])
    _Validator().feed(html)  # raises on malformed markup
    assert html.startswith("<!DOCTYPE html>")
    assert "http://" not in html.replace("https://", "")  # no external http resources
    assert "<link" not in html and "src=" not in html  # no external assets
    assert "Apply ↗" in html
    assert "https://account.amazon.com/jobs/1/apply" in html  # apply_url surfaced
    assert "Outreach message" in html and "copyMsg" in html


def test_render_html_escapes_untrusted_content():
    html = render_html(_profile(), [_match(title="Engineer <script>alert(1)</script>", company="A & B")])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    assert "A &amp; B" in html


def test_render_html_handles_no_matches():
    html = render_html(_profile(), [])
    _Validator().feed(html)
    assert "No matches found" in html
