from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass, field

from jobhunter.models import JobPosting

# Hosts that belong to an ATS/aggregator, not the employer — never treat these
# as the company domain for email inference.
_ATS_HOSTS = (
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "workday.com",
    "amazon.jobs",
    "ycombinator.com",
    "news.ycombinator.com",
    "remoteok.com",
    "remotive.com",
    "linkedin.com",
    "indeed.com",
    "glassdoor.com",
    "google.com",
    "consider.com",
    "jobs.a16z.com",
    "boards.greenhouse.io",
)

# Job text → the team keyword used to find a hiring manager / team lead.
_TEAM_KEYWORDS = (
    ("machine learning", "machine learning"),
    ("ml ", "machine learning"),
    ("research scien", "research"),
    ("research eng", "research"),
    ("applied scien", "applied science"),
    ("data scien", "data science"),
    ("infrastructure", "infrastructure"),
    ("platform", "platform"),
    ("backend", "engineering"),
    ("frontend", "engineering"),
    ("full stack", "engineering"),
    ("security", "security"),
    ("ai ", "ai"),
)

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_NOISE_EMAIL = ("example.", "sentry.io", "@2x", "@3x", "yourcompany", "domain.com", ".png", ".jpg")


@dataclass(frozen=True)
class ContactSuggestions:
    """Ways to reach a human about one job."""

    linkedin_searches: tuple[tuple[str, str], ...] = ()  # (label, url)
    emails_found: tuple[str, ...] = ()                    # extracted from the posting
    inferred_emails: tuple[str, ...] = ()                 # role-based, from the company domain
    company_domain: str | None = None

    @property
    def primary_email(self) -> str | None:
        if self.emails_found:
            return self.emails_found[0]
        return self.inferred_emails[0] if self.inferred_emails else None


def suggest_contacts(job: JobPosting) -> ContactSuggestions:
    company = (job.company or "").strip()
    team = _team_for(job)
    searches = _linkedin_searches(company, team) if company else ()
    found = _emails_in_text(job.description)
    domain = _company_domain(job)
    inferred = _role_emails(domain) if domain else ()
    return ContactSuggestions(
        linkedin_searches=searches,
        emails_found=found,
        inferred_emails=inferred,
        company_domain=domain,
    )


def _team_for(job: JobPosting) -> str:
    haystack = " ".join((job.title, " ".join(job.tags))).lower()
    for needle, label in _TEAM_KEYWORDS:
        if needle in haystack:
            return label
    return "engineering"


def _linkedin_searches(company: str, team: str) -> tuple[tuple[str, str], ...]:
    def url(keywords: str) -> str:
        q = urllib.parse.urlencode({"keywords": keywords})
        return f"https://www.linkedin.com/search/results/people/?{q}"

    return (
        ("Recruiter", url(f"{company} technical recruiter")),
        (f"{team.title()} hiring manager", url(f"{company} {team} hiring manager")),
        (f"Head of {team.title()}", url(f"{company} head of {team}")),
    )


def _emails_in_text(text: str) -> tuple[str, ...]:
    if not text:
        return ()
    seen: list[str] = []
    for match in _EMAIL_RE.findall(text):
        email = match.strip(".")
        low = email.lower()
        if any(noise in low for noise in _NOISE_EMAIL):
            continue
        if email not in seen:
            seen.append(email)
    return tuple(seen[:5])


def _company_domain(job: JobPosting) -> str | None:
    raw = job.raw if isinstance(job.raw, dict) else {}
    for key in ("companyDomain", "company_domain", "domain", "companyUrl", "company_url"):
        value = raw.get(key)
        if isinstance(value, str) and "." in value:
            host = _registrable_host(value)
            if host and not _is_ats_host(host):
                return host
    for url in (job.url, raw.get("applyUrl"), raw.get("url_next_step")):
        if isinstance(url, str):
            host = _registrable_host(url)
            if host and not _is_ats_host(host):
                return host
    return None


def _registrable_host(value: str) -> str | None:
    candidate = value if "://" in value else f"//{value}"
    host = urllib.parse.urlparse(candidate).netloc.lower().split("@")[-1].split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    return host or None


def _is_ats_host(host: str) -> bool:
    return any(host == ats or host.endswith("." + ats) for ats in _ATS_HOSTS)


def _role_emails(domain: str) -> tuple[str, ...]:
    return tuple(f"{prefix}@{domain}" for prefix in ("careers", "jobs", "recruiting", "talent"))
