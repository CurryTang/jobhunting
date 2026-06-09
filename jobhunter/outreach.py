from __future__ import annotations

import re

from jobhunter.models import JobMatch, UserProfile

# Raw-payload keys that point at the actual application page, in priority
# order. Sources keep their original records in JobPosting.raw, so the apply
# link survives normalization even when job.url is the listing page.
_APPLY_URL_RAW_KEYS = (
    "url_next_step",  # amazon
    "apply_url",      # remoteok, google
    "applyUrl",       # yc, a16z, lever
    "job_url_direct",  # jobspy
    "absolute_url",   # greenhouse
    "hostedUrl",      # lever fallback
)

# Matched-term annotations added by scoring that are not actual skills.
_NON_SKILL_TERMS = {
    "remote",
    "remote preferred",
    "stale posting",
    "aging posting",
    "quant finance evidence",
    "remote-only but onsite preferred",
}


def resolve_apply_url(match: JobMatch) -> str:
    raw = match.job.raw if isinstance(match.job.raw, dict) else {}
    for key in _APPLY_URL_RAW_KEYS:
        value = raw.get(key)
        if isinstance(value, str) and value.startswith("http"):
            return value
    return match.job.url


def build_outreach_message(profile: UserProfile, match: JobMatch) -> str:
    """Compose a short, sendable greeting tailored to one job match."""

    job = match.job
    name = profile.name or "a candidate"
    headline = (profile.headline or "").strip()
    skills = _talking_points(profile, match)
    link = _portfolio_link(profile)
    company = _display_company(job.company)

    intro = f"Hi {company} team, I'm {name}"
    if headline and headline.lower() not in name.lower():
        intro += f", {_indefinite(headline)}"
    intro += "."

    if skills:
        fit = f" My recent work on {_join(skills)} lines up closely with your {job.title} opening."
    else:
        fit = f" My background matches your {job.title} opening well."

    closing = " I'd love to connect and share how I could contribute."
    if link:
        closing += f" Portfolio: {link}"
    return intro + fit + closing


def _talking_points(profile: UserProfile, match: JobMatch, *, limit: int = 3) -> list[str]:
    # Skills and focus highlights read naturally after "my recent work on";
    # role names ("software engineer") do not, so they are excluded.
    profile_terms = {term.lower() for term in (*profile.skills, *profile.preferences.focus_highlights)}
    role_terms = {term.lower() for term in (*profile.roles, *profile.preferences.target_roles)}
    points: list[str] = []
    for term in match.matched_terms:
        normalized = term.lower()
        if normalized in _NON_SKILL_TERMS or normalized in role_terms or normalized == (profile.seniority or ""):
            continue
        if normalized in profile_terms and normalized not in (p.lower() for p in points):
            points.append(term)
        if len(points) >= limit:
            break
    if not points:
        points = [skill for skill in profile.skills[:limit]]
    return points[:limit]


def _display_company(company: str) -> str:
    # Legal suffixes read badly in a greeting ("Amazon.com Services LLC team").
    cleaned = re.sub(r"\s*[,.]?\s*\b(incorporated|inc|llc|ltd|corp|corporation|co)\b\.?\s*$", "", company, flags=re.I)
    return cleaned.strip(" ,.") or company


def _portfolio_link(profile: UserProfile) -> str | None:
    for link in profile.links:
        if "github.com" in link or "linkedin.com" in link:
            return link
    return profile.links[0] if profile.links else None


def _join(terms: list[str]) -> str:
    if len(terms) == 1:
        return terms[0]
    return ", ".join(terms[:-1]) + " and " + terms[-1]


def _indefinite(headline: str) -> str:
    article = "an" if re.match(r"[aeiou]", headline, re.I) else "a"
    return f"{article} {headline}"
