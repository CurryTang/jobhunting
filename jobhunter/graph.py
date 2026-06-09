from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Iterable

from jobhunter.models import JobMatch, UserProfile
from jobhunter.storage import job_key


class KuzuJobGraphStore:
    """Embedded graph projection for jobs, skills, companies, and candidate matches."""

    def __init__(self, path: str | Path) -> None:
        try:
            import kuzu
        except ImportError as exc:  # pragma: no cover - optional graph dependency.
            raise RuntimeError("Kuzu graph support requires `python -m pip install -U '.[graph]'`.") from exc
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._kuzu = kuzu

    def project_matches(self, profile: UserProfile, matches: list[JobMatch]) -> None:
        conn = self._connection()
        _initialize_schema(conn)
        profile_key = _profile_key(profile)
        conn.execute(
            f"""
            MERGE (p:CandidateProfile {{profile_key: {_q(profile_key)}}})
            SET p.name = {_q(profile.name or "")}, p.headline = {_q(profile.headline or "")}
            """
        )
        for skill in _profile_skills(profile):
            self._merge_skill(conn, skill)
            conn.execute(
                f"""
                MATCH (p:CandidateProfile), (s:Skill)
                WHERE p.profile_key = {_q(profile_key)} AND s.name = {_q(skill)}
                MERGE (p)-[:HAS_SKILL]->(s)
                """
            )

        for rank, match in enumerate(matches, start=1):
            job = match.job
            key = job_key(job)
            company = _normalize_label(job.company)
            conn.execute(
                f"""
                MERGE (j:Job {{job_key: {_q(key)}}})
                SET j.title = {_q(job.title)}, j.company = {_q(job.company)}, j.url = {_q(job.url)}, j.source = {_q(job.source)}
                """
            )
            conn.execute(f"MERGE (c:Company {{name: {_q(company)}}})")
            conn.execute(
                f"""
                MATCH (j:Job), (c:Company)
                WHERE j.job_key = {_q(key)} AND c.name = {_q(company)}
                MERGE (j)-[:AT_COMPANY]->(c)
                """
            )
            conn.execute(
                f"""
                MATCH (p:CandidateProfile), (j:Job)
                WHERE p.profile_key = {_q(profile_key)} AND j.job_key = {_q(key)}
                MERGE (p)-[r:MATCHED]->(j)
                SET r.score = {float(match.score)}, r.rank = {rank}
                """
            )
            for skill in _job_skills(profile, match):
                self._merge_skill(conn, skill)
                conn.execute(
                    f"""
                    MATCH (j:Job), (s:Skill)
                    WHERE j.job_key = {_q(key)} AND s.name = {_q(skill)}
                    MERGE (j)-[r:MENTIONS]->(s)
                    SET r.weight = 1.0
                    """
                )

    def skill_overlap_boosts(self, profile: UserProfile, *, weight: float = 0.35) -> dict[str, float]:
        conn = self._connection()
        _initialize_schema(conn)
        profile_key = _profile_key(profile)
        result = conn.execute(
            f"""
            MATCH (p:CandidateProfile)-[:HAS_SKILL]->(s:Skill)<-[:MENTIONS]-(j:Job)
            WHERE p.profile_key = {_q(profile_key)}
            RETURN j.job_key, count(s) * {float(weight)} AS boost
            """
        )
        boosts: dict[str, float] = {}
        while result.has_next():
            job_key_value, boost = result.get_next()
            boosts[str(job_key_value)] = float(boost)
        return boosts

    def _connection(self):
        return self._kuzu.Connection(self._kuzu.Database(str(self.path)))

    def _merge_skill(self, conn, skill: str) -> None:
        conn.execute(f"MERGE (s:Skill {{name: {_q(skill)}}})")


def apply_graph_boosts(matches: list[JobMatch], boosts: dict[str, float]) -> list[JobMatch]:
    boosted: list[JobMatch] = []
    for match in matches:
        boost = boosts.get(job_key(match.job), 0.0)
        if boost <= 0:
            boosted.append(match)
            continue
        boosted.append(
            replace(
                match,
                score=round(match.score + boost, 2),
                matched_terms=tuple(dict.fromkeys((*match.matched_terms, "graph skill overlap"))),
                rationale=f"{match.rationale}; graph skill overlap +{boost:.2f}",
            )
        )
    return sorted(boosted, key=lambda item: (-item.score, item.job.company, item.job.title))


def _initialize_schema(conn) -> None:
    conn.execute(
        "CREATE NODE TABLE IF NOT EXISTS CandidateProfile(profile_key STRING, name STRING, headline STRING, PRIMARY KEY(profile_key))"
    )
    conn.execute(
        "CREATE NODE TABLE IF NOT EXISTS Job(job_key STRING, title STRING, company STRING, url STRING, source STRING, PRIMARY KEY(job_key))"
    )
    conn.execute("CREATE NODE TABLE IF NOT EXISTS Company(name STRING, PRIMARY KEY(name))")
    conn.execute("CREATE NODE TABLE IF NOT EXISTS Skill(name STRING, PRIMARY KEY(name))")
    conn.execute("CREATE REL TABLE IF NOT EXISTS HAS_SKILL(FROM CandidateProfile TO Skill)")
    conn.execute("CREATE REL TABLE IF NOT EXISTS MENTIONS(FROM Job TO Skill, weight DOUBLE)")
    conn.execute("CREATE REL TABLE IF NOT EXISTS AT_COMPANY(FROM Job TO Company)")
    conn.execute("CREATE REL TABLE IF NOT EXISTS MATCHED(FROM CandidateProfile TO Job, score DOUBLE, rank INT64)")


def _profile_key(profile: UserProfile) -> str:
    if profile.name:
        return _normalize_label(profile.name)
    if profile.links:
        return _normalize_label(profile.links[0])
    return _normalize_label(profile.headline or "candidate")


def _profile_skills(profile: UserProfile) -> tuple[str, ...]:
    return tuple(_normalize_label(skill) for skill in (*profile.skills, *profile.preferences.focus_highlights) if skill)


def _job_skills(profile: UserProfile, match: JobMatch) -> tuple[str, ...]:
    haystack = " ".join(
        (
            match.job.title,
            match.job.company,
            match.job.description,
            " ".join(match.job.tags),
            " ".join(match.matched_terms),
        )
    ).lower()
    skills = []
    for skill in _profile_skills(profile):
        if skill and skill.lower() in haystack:
            skills.append(skill)
    for term in match.matched_terms:
        if term and term != "graph skill overlap":
            skills.append(_normalize_label(term))
    return tuple(dict.fromkeys(skills))


def _normalize_label(value: str) -> str:
    return " ".join(str(value).lower().split())


def _q(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'
