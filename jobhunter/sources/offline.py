from __future__ import annotations

from jobhunter.models import JobPosting, SearchQuery, UserProfile
from jobhunter.sources.base import JobPlatform


class OfflineDemoPlatform(JobPlatform):
    """Deterministic source for tests and demos without network access."""

    name = "offline"

    def __init__(self) -> None:
        self.jobs = (
            JobPosting(
                source=self.name,
                source_id="demo-1",
                title="Machine Learning Engineer",
                company="Vector Labs",
                url="https://example.com/jobs/ml-engineer",
                location="Remote US",
                description="Build Python and PyTorch systems for LLM data products.",
                tags=("machine learning", "python", "remote"),
                salary="$150k-$190k",
            ),
            JobPosting(
                source=self.name,
                source_id="demo-2",
                title="Frontend Engineer",
                company="Canvas Tools",
                url="https://example.com/jobs/frontend",
                location="New York",
                description="React and TypeScript product engineering for design tools.",
                tags=("react", "typescript"),
            ),
            JobPosting(
                source=self.name,
                source_id="demo-3",
                title="Data Platform Engineer",
                company="Warehouse AI",
                url="https://example.com/jobs/data-platform",
                location="Remote",
                description="Own SQL, Python, orchestration, and distributed data pipelines.",
                tags=("data", "python", "sql"),
            ),
        )

    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        terms = [term.lower() for term in (query.text, query.role or "", *query.skills)]
        matches = []
        for job in self.jobs:
            haystack = " ".join((job.title, job.company, job.description, " ".join(job.tags))).lower()
            if any(term and term in haystack for term in terms):
                matches.append(job)
        return matches[:limit] or list(self.jobs[:limit])
