from __future__ import annotations

from abc import ABC, abstractmethod

from jobhunter.models import JobPosting, SearchQuery, UserProfile


class JobPlatform(ABC):
    """Abstract interface for all job hunting platforms."""

    name: str

    @abstractmethod
    def search(
        self,
        query: SearchQuery,
        profile: UserProfile,
        *,
        limit: int = 20,
    ) -> list[JobPosting]:
        """Return normalized job postings for a generated query."""
