from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import datetime, timezone

from jobhunter.models import JobMatch, JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform
from jobhunter.storage import job_key
from jobhunter.trace import NULL_TRACER, TrajectoryLogger

QUANT_ROLE_TERMS = (
    "quantitative researcher",
    "quant researcher",
    "quantitative research",
    "quant research",
    "quantitative research engineer",
    "quant research engineer",
    "machine learning researcher",
)

QUANT_DOMAIN_TERMS = (
    "quant",
    "quantitative",
    "alpha",
    "trading",
    "market",
    "markets",
    "portfolio",
    "statistical arbitrage",
    "systematic",
    "time series",
    "time-series",
    "finance",
    "financial",
    "fintech",
    "equities",
    "futures",
    "options",
    "derivatives",
)

STRONG_QUANT_DOMAIN_TERMS = (
    "quant",
    "quantitative",
    "alpha",
    "trading",
    "statistical arbitrage",
    "systematic",
    "time series",
    "time-series",
    "equities",
    "futures",
    "derivatives",
)

SOFT_QUANT_DOMAIN_TERMS = (
    "market",
    "markets",
    "portfolio",
    "finance",
    "financial",
    "fintech",
    "options",
)

LOW_SIGNAL_TECH_TITLE_TERMS = (
    "ai trainer",
    "trainer",
    "annotator",
    "annotation",
    "data annotation",
    "video editor",
    "editor",
    "writer",
    "copywriter",
    "marketing",
    "sales",
    "account executive",
    "customer success",
    "recruiter",
    "product manager",
    "designer",
    "operations",
)


class QueryPlanner:
    """Generate concrete search queries from a structured profile."""

    def plan(self, profile: UserProfile, *, max_queries: int = 8) -> list[SearchQuery]:
        has_explicit_roles = bool(profile.preferences.target_roles)
        roles = list(profile.preferences.target_roles) or list(profile.roles) or self._roles_from_skills(profile)
        focus_terms = _focus_terms(profile)
        all_skills = _merge_preserving_order(focus_terms, list(profile.skills))
        skills = all_skills[:6]
        locations = list(profile.preferences.preferred_locations) or list(profile.locations) or ["remote"]
        remote = profile.preferences.remote if profile.preferences.remote is not None else "remote" in locations
        queries: list[SearchQuery] = []

        if _is_quant_search(profile):
            queries.extend(_quant_queries(all_skills, locations, remote))

        for role in roles[:3]:
            role_skills = _role_skill_pool(role, all_skills, profile)
            text = _compose_role_query(role, role_skills)
            queries.append(
                SearchQuery(
                    text=text,
                    role=role,
                    skills=role_skills,
                    location=locations[0] if locations else None,
                    remote=remote,
                )
            )

        if skills and not has_explicit_roles:
            queries.append(SearchQuery(text=" ".join(skills[:4]), skills=tuple(skills[:4]), remote=remote))
        # Compact skill-pair queries stay in the plan even with explicit
        # roles: board taxonomies often differ from the user's role wording,
        # and these focused queries keep sparse sources contributing.
        queries.extend(_skill_pair_queries(skills, remote=remote, location=locations[0] if locations else None))

        if profile.keywords and not has_explicit_roles:
            queries.append(SearchQuery(text=" ".join(profile.keywords[:4]), remote=remote))

        return _dedupe_queries(queries)[:max_queries]

    def _roles_from_skills(self, profile: UserProfile) -> list[str]:
        skills = set(profile.skills)
        if {"pytorch", "tensorflow", "machine learning", "llm", "nlp"} & skills:
            return ["machine learning engineer"]
        if {"react", "typescript", "frontend"} & skills:
            return ["frontend engineer"]
        if {"sql", "data science", "analytics"} & skills:
            return ["data engineer"]
        return ["software engineer"]


class AgenticQueryPlanner(QueryPlanner):
    """Broad role-family planner for recall-heavy search-platform runs."""

    def plan(self, profile: UserProfile, *, max_queries: int = 24) -> list[SearchQuery]:
        queries = super().plan(profile, max_queries=max_queries)
        preference_text = _normalize(
            " ".join(
                (
                    *profile.preferences.target_roles,
                    *profile.preferences.industries,
                    *profile.preferences.focus_highlights,
                    profile.preferences.notes or "",
                )
            )
        )
        wants_broad = (profile.preferences.result_count or 0) >= 50
        if wants_broad or any(term in preference_text for term in ("quant", "software", "mle", "machine learning", "sde")):
            locations = list(profile.preferences.preferred_locations) or list(profile.locations) or [None]
            location = locations[0] if locations else None
            remote = profile.preferences.remote
            queries.extend(
                [
                    SearchQuery("machine learning engineer python", "machine learning engineer", ("python", "machine learning"), location, remote),
                    SearchQuery("machine learning engineer llm", "machine learning engineer", ("llm", "machine learning"), location, remote),
                    SearchQuery("applied machine learning engineer", "machine learning engineer", ("machine learning",), location, remote),
                    SearchQuery("ai engineer llm agents", "machine learning engineer", ("llm", "agents"), location, remote),
                    SearchQuery("research engineer machine learning", "research engineer", ("machine learning", "research"), location, remote),
                    SearchQuery("research scientist machine learning", "research scientist", ("machine learning", "research"), location, remote),
                    SearchQuery("software engineer python backend", "software engineer", ("python", "backend"), location, remote),
                    SearchQuery("software engineer infrastructure", "software engineer", ("infrastructure",), location, remote),
                    SearchQuery("backend software engineer distributed systems", "software engineer", ("backend", "distributed systems"), location, remote),
                    SearchQuery("full stack software engineer startup", "software engineer", ("javascript", "backend"), location, remote),
                    SearchQuery("quantitative researcher machine learning", "quantitative researcher", ("machine learning", "python"), location, remote),
                    SearchQuery("quant research engineer python", "quant research engineer", ("python", "machine learning"), location, remote),
                    SearchQuery("quantitative developer python", "software engineer", ("python",), location, remote),
                    SearchQuery("systematic trading machine learning", "quantitative researcher", ("machine learning",), location, remote),
                    SearchQuery("alpha researcher machine learning", "quantitative researcher", ("machine learning",), location, remote),
                    SearchQuery("llm infrastructure engineer", "software engineer", ("llm", "infrastructure"), location, remote),
                ]
            )
        return _dedupe_queries(queries)[:max_queries]


class JobSearchAgent:
    """Search multiple platforms, deduplicate postings, and rank profile fit."""

    def __init__(
        self,
        platforms: Sequence[JobPlatform],
        *,
        planner: QueryPlanner | None = None,
        tracer: TrajectoryLogger | None = None,
    ) -> None:
        self.platforms = list(platforms)
        self.planner = planner or QueryPlanner()
        self.tracer = tracer or NULL_TRACER
        self.errors: list[str] = []

    def search(
        self,
        profile: UserProfile,
        *,
        limit: int = 10,
        per_query_limit: int = 10,
        max_queries: int | None = None,
    ) -> list[JobMatch]:
        queries = self.planner.plan(profile, max_queries=max_queries) if max_queries is not None else self.planner.plan(profile)
        seen: dict[str, JobMatch] = {}
        self.errors = []
        self.tracer.log(
            "queries_planned",
            planner=type(self.planner).__name__,
            queries=[query.text for query in queries],
        )

        for query in queries:
            for platform in self.platforms:
                try:
                    jobs = platform.search(query, profile, limit=per_query_limit)
                except Exception as exc:  # pragma: no cover - exercised in live runs.
                    self.errors.append(f"{platform.name} failed for query '{query.text}': {exc}")
                    self.tracer.log("source_error", source=platform.name, query=query.text, error=str(exc))
                    continue
                kept = 0
                for job in jobs:
                    if has_location_mismatch(job, profile):
                        continue
                    if _has_excluded_term(job, profile):
                        continue
                    match = score_job(job, profile, query)
                    if match.score <= 0:
                        continue
                    if not _has_core_match(match, profile):
                        continue
                    kept += 1
                    key = job_key(job)
                    current = seen.get(key)
                    if current is None or match.score > current.score:
                        seen[key] = match
                self.tracer.log(
                    "source_search",
                    source=platform.name,
                    query=query.text,
                    fetched=len(jobs),
                    kept=kept,
                    unique_jobs_so_far=len(seen),
                )

        ranked = _diversify(
            sorted(seen.values(), key=lambda match: (-match.score, match.job.company, match.job.title)),
            limit=limit,
        )
        self.tracer.log(
            "ranked_results",
            unique_jobs=len(seen),
            returned=len(ranked),
            results=[
                {
                    "rank": index,
                    "score": match.score,
                    "title": match.job.title,
                    "company": match.job.company,
                    "source": match.job.source,
                    "location": match.job.location,
                    "posted_at": match.job.posted_at.isoformat() if match.job.posted_at else None,
                    "url": match.job.url,
                    "matched_terms": list(match.matched_terms),
                }
                for index, match in enumerate(ranked, start=1)
            ],
        )
        return ranked


def _diversify(matches_sorted: list[JobMatch], *, limit: int, per_source_floor: int = 2) -> list[JobMatch]:
    """Reserve a small floor per source before filling globally by score.

    Prevents one verbose source from monopolizing the final list while never
    promoting clearly weak results: floor picks must score at least 20% of
    the best match.
    """

    if limit <= 0 or len(matches_sorted) <= limit:
        return matches_sorted[:limit]
    min_floor_score = max(1.0, matches_sorted[0].score * 0.2)
    selected: list[JobMatch] = []
    selected_ids: set[int] = set()
    per_source: dict[str, int] = {}
    for match in matches_sorted:
        if len(selected) >= limit:
            break
        source = match.job.source
        if per_source.get(source, 0) < per_source_floor and match.score >= min_floor_score:
            selected.append(match)
            selected_ids.add(id(match))
            per_source[source] = per_source.get(source, 0) + 1
    for match in matches_sorted:
        if len(selected) >= limit:
            break
        if id(match) not in selected_ids:
            selected.append(match)
            selected_ids.add(id(match))
    return sorted(selected, key=lambda match: (-match.score, match.job.company, match.job.title))


def score_job(job: JobPosting, profile: UserProfile, query: SearchQuery) -> JobMatch:
    haystack = _normalize(" ".join((job.title, job.company, job.description, job.location or "", " ".join(job.tags))))
    weighted_terms: dict[str, tuple[str, float]] = {}
    _add_weighted_terms(weighted_terms, ((role, 4.0) for role in profile.preferences.target_roles))
    _add_weighted_terms(weighted_terms, ((alias, 3.5) for role in profile.preferences.target_roles for alias in _role_aliases(role)))
    _add_weighted_terms(weighted_terms, ((term, 2.5) for term in _focus_terms(profile)))
    _add_weighted_terms(weighted_terms, ((role, 3.0) for role in profile.roles))
    _add_weighted_terms(weighted_terms, ((skill, 2.0) for skill in profile.skills))
    if not profile.preferences.target_roles:
        _add_weighted_terms(weighted_terms, ((keyword, 0.75) for keyword in profile.keywords[:10]))
    if query.role:
        _add_weighted_terms(weighted_terms, ((query.role, 2.0),))
    _add_weighted_terms(weighted_terms, ((skill, 1.0) for skill in query.skills))
    if _is_quant_search(profile):
        _add_weighted_terms(weighted_terms, ((term, 1.5) for term in STRONG_QUANT_DOMAIN_TERMS))
        _add_weighted_terms(weighted_terms, ((term, 0.25) for term in SOFT_QUANT_DOMAIN_TERMS))

    score = 0.0
    matched: list[str] = []
    for term, weight in weighted_terms.values():
        term_norm = _normalize(term)
        if term_norm and re.search(r"(?<![a-z0-9])" + re.escape(term_norm) + r"(?![a-z0-9])", haystack):
            score += weight
            matched.append(term)

    if profile.seniority and _should_score_seniority(profile) and profile.seniority in haystack:
        score += 1.0
        matched.append(profile.seniority)
    if "remote" in profile.locations and "remote" in haystack:
        score += 1.0
        matched.append("remote")
    if profile.preferences.remote is True and "remote" in haystack:
        score += 1.0
        matched.append("remote preferred")
    for industry in profile.preferences.industries:
        if _contains_term(haystack, industry):
            score += 1.25
            matched.append(industry)
    for stage in profile.preferences.company_stages:
        if _contains_term(haystack, stage):
            score += 1.0
            matched.append(stage)
    if _is_quant_search(profile):
        if _has_quant_evidence(haystack):
            score += 2.0
            matched.append("quant finance evidence")
        else:
            score -= 2.5
    if profile.preferences.min_salary and job.salary:
        score += _salary_fit_bonus(job.salary, profile.preferences.min_salary)
    if has_location_mismatch(job, profile):
        score -= 4.0
    if job.salary:
        score += 0.25
    age_days = _posting_age_days(job)
    if age_days is not None:
        if age_days > 60:
            score -= 3.0
            matched.append("stale posting")
        elif age_days > 30:
            score -= 1.5
            matched.append("aging posting")
    if profile.preferences.remote is False and _is_remote_only_location(job.location):
        score -= 3.0
        matched.append("remote-only but onsite preferred")

    unique_terms = tuple(dict.fromkeys(matched))
    rationale = "Matched " + ", ".join(unique_terms[:8]) if unique_terms else "Weak keyword fit"
    if has_location_mismatch(job, profile):
        rationale += "; location may not fit profile"
    return JobMatch(job=job, score=round(score, 2), matched_terms=unique_terms, query=query, rationale=rationale)


def _dedupe_queries(queries: Sequence[SearchQuery]) -> list[SearchQuery]:
    seen: set[str] = set()
    deduped: list[SearchQuery] = []
    for query in queries:
        key = _normalize(query.text)
        if key and key not in seen:
            seen.add(key)
            deduped.append(query)
    return deduped


def _add_weighted_terms(target: dict[str, tuple[str, float]], terms: Iterable[tuple[str, float]]) -> None:
    for term, weight in terms:
        term_norm = _normalize(term)
        if not term_norm:
            continue
        current = target.get(term_norm)
        if current is None or weight > current[1]:
            target[term_norm] = (term, weight)


def _compose_role_query(role: str, skills: Sequence[str], *, max_extra_terms: int = 2) -> str:
    role_norm = _normalize(role)
    extras: list[str] = []
    for skill in skills:
        skill_norm = _normalize(skill)
        if not skill_norm or skill_norm in role_norm:
            continue
        if any(skill_norm == existing or skill_norm in existing or existing in skill_norm for existing in extras):
            continue
        extras.append(skill)
        if len(extras) >= max_extra_terms:
            break
    return " ".join(item for item in (role, *extras) if item)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _contains_term(haystack: str, term: str) -> bool:
    term_norm = _normalize(term)
    return bool(term_norm and re.search(r"(?<![a-z0-9])" + re.escape(term_norm) + r"(?![a-z0-9])", haystack))


def _has_core_match(match: JobMatch, profile: UserProfile) -> bool:
    matched = {_normalize(term) for term in match.matched_terms}
    target_role_terms = {_normalize(term) for term in profile.preferences.target_roles}
    role_terms = {_normalize(term) for term in profile.roles}
    technical_skill_terms = {_normalize(term) for term in profile.skills if _normalize(term) not in {"research"}}
    if _has_low_signal_technical_title(match.job, profile):
        return False
    if target_role_terms and not _has_role_family_fit(match.job, profile):
        if _is_quant_search(profile):
            return False
        # Adjacent technical match: keep results that hit several profile
        # skills even when the title family differs, so sparse sources keep
        # contributing. Ranking still favors true role-family fits.
        return len(matched & technical_skill_terms) >= 2
    if _is_quant_search(profile):
        has_quant_target = bool(matched & target_role_terms)
        has_quant_domain = "quant finance evidence" in matched
        has_technical_fit = bool(matched & role_terms) or bool(matched & technical_skill_terms)
        return has_quant_target or (has_quant_domain and has_technical_fit)
    return bool(matched & target_role_terms) or bool(matched & role_terms) or bool(matched & technical_skill_terms)


def _is_quant_search(profile: UserProfile) -> bool:
    preference_text = " ".join(
        (
            *profile.preferences.target_roles,
            *profile.preferences.industries,
            profile.preferences.notes or "",
        )
    )
    text = _normalize(preference_text)
    return any(term in text for term in ("quant", "trading", "finance", "financial", "alpha"))


def _has_quant_evidence(haystack: str) -> bool:
    return any(_contains_term(haystack, term) for term in STRONG_QUANT_DOMAIN_TERMS)


def _should_score_seniority(profile: UserProfile) -> bool:
    if profile.seniority != "intern":
        return True
    job_type_text = _normalize(" ".join(profile.preferences.job_types))
    preference_text = _normalize(" ".join((*profile.preferences.target_roles, profile.preferences.notes or "")))
    return any(term in job_type_text or term in preference_text for term in ("intern", "internship"))


def _has_role_family_fit(job: JobPosting, profile: UserProfile) -> bool:
    target_text = _normalize(" ".join(profile.preferences.target_roles))
    title_text = _normalize(" ".join((job.title, job.company)))
    body_text = _normalize(" ".join((job.title, job.company, job.description, " ".join(job.tags))))

    if any(_contains_term(body_text, role) for role in profile.preferences.target_roles):
        return True
    if any(_contains_term(body_text, alias) for role in profile.preferences.target_roles for alias in _role_aliases(role)):
        return True

    wants_quant = any(term in target_text for term in ("quant", "trading", "alpha"))
    wants_ml = any(term in target_text for term in ("machine learning", "ml ", "research scientist", "research engineer", "ai researcher"))
    wants_software = any(term in target_text for term in ("software", "backend", "platform", "infrastructure", "full stack", "sde", "developer"))

    if wants_quant and _has_quant_evidence(body_text):
        if any(_contains_term(title_text, term) for term in ("researcher", "research", "engineer", "developer", "scientist")):
            return True
        if any(_contains_term(body_text, term) for term in ("research", "signal", "model", "machine learning", "python")):
            return True

    if wants_ml and any(
        _contains_term(title_text, term)
        for term in (
            "machine learning engineer",
            "ml engineer",
            "machine learning researcher",
            "research scientist",
            "research engineer",
            "ai engineer",
            "ai researcher",
            "data scientist",
        )
    ):
        return True

    if wants_software and any(
        _contains_term(title_text, term)
        for term in (
            "software engineer",
            "backend engineer",
            "platform engineer",
            "infrastructure engineer",
            "full stack engineer",
            "full-stack engineer",
            "developer",
        )
    ):
        return True

    if wants_software and _contains_term(title_text, "engineer") and any(
        _contains_term(title_text, term) for term in ("backend", "platform", "infrastructure", "full stack", "full-stack", "systems")
    ):
        return True

    return False


def _role_aliases(role: str) -> tuple[str, ...]:
    role_norm = _normalize(role)
    aliases: list[str] = []
    if "machine learning engineer" in role_norm or role_norm == "ml engineer":
        aliases.extend(("ml engineer", "machine learning researcher", "ml researcher", "applied scientist", "ai engineer"))
    if "research scientist" in role_norm:
        aliases.extend(("machine learning researcher", "ml researcher", "ai research scientist", "applied scientist"))
    if "research engineer" in role_norm:
        aliases.extend(("ml researcher", "machine learning researcher", "ai research engineer", "applied scientist"))
    if "software engineer" in role_norm:
        aliases.extend(("sde", "software developer"))
    if "quantitative researcher" in role_norm or "quant researcher" in role_norm:
        aliases.extend(("quant researcher", "quantitative research scientist", "alpha researcher"))
    if "quant research engineer" in role_norm or "quantitative research engineer" in role_norm:
        aliases.extend(("quantitative research engineer", "quant developer", "quantitative developer"))
    return tuple(dict.fromkeys(alias for alias in aliases if alias != role_norm))


def _has_low_signal_technical_title(job: JobPosting, profile: UserProfile) -> bool:
    # Fall back to inferred profile roles so spammy titles ("AI Trainer",
    # sales, annotation work) are filtered even before the user records
    # explicit target roles.
    target_text = _normalize(" ".join(profile.preferences.target_roles or profile.roles))
    wants_technical = any(
        term in target_text
        for term in (
            "engineer",
            "developer",
            "researcher",
            "scientist",
            "quant",
            "software",
            "machine learning",
            "ml ",
            "sde",
        )
    )
    if not wants_technical:
        return False
    title_text = _normalize(job.title)
    return any(_contains_term(title_text, term) for term in LOW_SIGNAL_TECH_TITLE_TERMS)


def _focus_terms(profile: UserProfile, *, limit: int = 6) -> list[str]:
    focus_text = _normalize(" ".join(profile.preferences.focus_highlights))
    if not focus_text:
        return []

    terms: list[str] = []
    for skill in profile.skills:
        skill_norm = _normalize(skill)
        if skill_norm and skill_norm in focus_text:
            terms.append(skill)
    for keyword in profile.keywords:
        keyword_norm = _normalize(keyword)
        if keyword_norm and keyword_norm in focus_text:
            terms.append(keyword)
    if len(terms) < limit:
        stop = {"with", "that", "this", "from", "your", "work", "project", "built", "using", "system"}
        for token in re.findall(r"[a-z][a-z0-9+#-]{3,}", focus_text):
            if token not in stop:
                terms.append(token)
    return _merge_preserving_order([], terms)[:limit]


def _role_skill_pool(role: str, skills: list[str], profile: UserProfile) -> tuple[str, ...]:
    role_norm = _normalize(role)
    focus = _focus_terms(profile, limit=2)
    if _is_quant_search(profile) and any(term in role_norm for term in ("quant", "researcher", "research scientist")):
        preferred = [
            "machine learning",
            "python",
            "research",
            "llm",
            "graph",
            "time series",
        ]
        archetype = [skill for skill in preferred if skill in skills or skill in {"machine learning", "time series"}]
        return tuple(_merge_preserving_order(focus, _merge_preserving_order(archetype, skills[:3]))[:4])
    if any(term in role_norm for term in ("machine learning", "ml engineer", "ai engineer")):
        return tuple(_merge_preserving_order(focus, _merge_preserving_order(["machine learning", "python", "llm"], skills[:3]))[:4])
    if any(term in role_norm for term in ("research scientist", "research engineer", "researcher")):
        return tuple(_merge_preserving_order(focus, _merge_preserving_order(["machine learning", "research", "python", "llm"], skills[:3]))[:4])
    if any(term in role_norm for term in ("software", "backend", "platform", "infrastructure", "sde", "developer")):
        return tuple(_merge_preserving_order(focus, _merge_preserving_order(["python", "backend", "infrastructure", "distributed systems"], skills[:3]))[:4])
    return tuple(skills[:3])


def _quant_queries(skills: list[str], locations: list[str], remote: bool | None) -> list[SearchQuery]:
    skill_set = set(skills)
    preferred_skills = tuple(
        skill
        for skill in ("machine learning", "python", "research", "llm", "graph")
        if skill in skill_set or skill in {"machine learning"}
    )[:3]
    location = locations[0] if locations else None
    return [
        SearchQuery(
            text="quantitative researcher machine learning python",
            role="quantitative researcher",
            skills=preferred_skills,
            location=location,
            remote=remote,
        ),
        SearchQuery(
            text="quant research engineer python machine learning",
            role="quantitative research engineer",
            skills=preferred_skills,
            location=location,
            remote=remote,
        ),
        SearchQuery(
            text="alpha research machine learning python",
            role="quant researcher",
            skills=preferred_skills,
            location=location,
            remote=remote,
        ),
    ]


def _skill_pair_queries(
    skills: list[str],
    *,
    remote: bool | None = True,
    location: str | None = None,
) -> list[SearchQuery]:
    skill_set = set(skills)
    pairs = (
        ("python", "llm"),
        ("graph", "llm"),
        ("graphs", "llm"),
        ("javascript", "node"),
        ("python", "mlsys"),
        ("llm", "agentic"),
    )
    queries: list[SearchQuery] = []
    for first, second in pairs:
        if first in skill_set and second in skill_set:
            queries.append(SearchQuery(text=f"{first} {second}", skills=(first, second), location=location, remote=remote))
    return queries


def _merge_preserving_order(first: list[str], second: list[str]) -> list[str]:
    return list(dict.fromkeys((*first, *second)))


def has_location_mismatch(job: JobPosting, profile: UserProfile) -> bool:
    desired_locations = profile.preferences.preferred_locations or profile.locations
    if not desired_locations or not job.location:
        return False
    desired = {_normalize(location) for location in desired_locations}
    location = _normalize(job.location)

    if any(item and item in location for item in desired if item not in {"remote", "remote us", "remote (us)", "united states", "usa"}):
        return False
    remote_wanted = profile.preferences.remote is True or "remote" in desired
    if remote_wanted and any(term in location for term in ("worldwide", "anywhere")):
        return False
    if remote_wanted and "remote" in location and not _remote_names_other_region(location, desired):
        # Plain "Remote" or a remote region compatible with the preference.
        return False
    if {"united states", "usa", "remote us", "remote (us)"} & desired:
        return not any(term in location for term in ("united states", "usa", "u.s.", "us", "worldwide", "anywhere"))
    return False


def _remote_names_other_region(location: str, desired: set[str]) -> bool:
    """True when a remote location pins a region outside the desired one.

    "Remote - Paris" must not satisfy a Remote-US preference, while plain
    "Remote", "Remote Worldwide", or "Remote - United States" should.
    """

    rest = re.sub(r"(?<![a-z0-9])remote(?![a-z0-9])", " ", location)
    rest = re.sub(r"[^a-z0-9. ]+", " ", rest)
    rest = re.sub(r"\s+", " ", rest).strip(" .-")
    if not rest:
        return False
    if any(term in rest for term in ("worldwide", "anywhere", "global")):
        return False
    if any(item and item in rest for item in desired if item != "remote"):
        return False
    if re.search(r"(?<![a-z0-9])(us|usa|u\.s\.|united states|north america|americas)(?![a-z0-9])", rest):
        return False
    return True


def _has_excluded_term(job: JobPosting, profile: UserProfile) -> bool:
    if not profile.preferences.excluded_terms:
        return False
    haystack = _normalize(" ".join((job.title, job.company, job.description, " ".join(job.tags))))
    # Word-boundary matching so excluding "go" does not reject "django".
    return any(_contains_term(haystack, term) for term in profile.preferences.excluded_terms)


def _posting_age_days(job: JobPosting) -> float | None:
    if job.posted_at is None:
        return None
    posted = job.posted_at if job.posted_at.tzinfo else job.posted_at.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - posted).total_seconds() / 86400


def _is_remote_only_location(location: str | None) -> bool:
    if not location:
        return False
    normalized = _normalize(location)
    has_remote = any(term in normalized for term in ("remote", "worldwide", "anywhere"))
    # Only explicit onsite/hybrid wording counts: strings like
    # "Remote, United States" are still remote-only postings.
    has_onsite_hint = any(term in normalized for term in ("hybrid", "onsite", "on-site", "in office", "in-office"))
    return has_remote and not has_onsite_hint


def _salary_fit_bonus(salary: str, minimum: int) -> float:
    values = [int(match) for match in re.findall(r"\d+", salary.replace(",", ""))]
    if not values:
        return 0.0
    # Salary strings often use compact K notation, so normalize likely annual numbers.
    normalized = [value * 1000 if value < 1000 else value for value in values]
    return 1.0 if max(normalized) >= minimum else -2.0
