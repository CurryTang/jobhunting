from jobhunter.contacts import suggest_contacts
from jobhunter.models import JobPosting


def test_inferred_emails_from_company_domain():
    job = JobPosting(
        source="a16z", source_id="1", title="Staff Machine Learning Engineer", company="Waymo",
        url="https://waymo.com/careers/123", raw={"companyDomain": "waymo.com"},
    )
    c = suggest_contacts(job)
    assert c.company_domain == "waymo.com"
    assert "careers@waymo.com" in c.inferred_emails
    assert c.primary_email == "careers@waymo.com"
    labels = [label for label, _ in c.linkedin_searches]
    assert "Recruiter" in labels
    assert any("Machine Learning" in label for label in labels)
    assert all(url.startswith("https://www.linkedin.com/search/results/people/") for _, url in c.linkedin_searches)


def test_emails_extracted_from_posting_text():
    job = JobPosting(
        source="hackernews", source_id="2", title="ML Engineer", company="Acme",
        url="https://news.ycombinator.com/item?id=1",
        description="We're hiring! Email jobs@acme.ai or alice@acme.ai. Skip logo@2x.png.",
    )
    c = suggest_contacts(job)
    assert c.emails_found == ("jobs@acme.ai", "alice@acme.ai")
    assert c.primary_email == "jobs@acme.ai"


def test_ats_host_is_not_treated_as_company_domain():
    job = JobPosting(
        source="greenhouse", source_id="3", title="Research Engineer, ML", company="Anthropic",
        url="https://boards.greenhouse.io/anthropic/jobs/3",
    )
    c = suggest_contacts(job)
    assert c.company_domain is None  # never infer emails from an ATS host
    assert c.inferred_emails == ()
    assert c.linkedin_searches  # but LinkedIn searches are still offered
