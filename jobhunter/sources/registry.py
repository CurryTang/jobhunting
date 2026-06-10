from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from jobhunter.sources.a16z import A16ZPlatform
from jobhunter.sources.base import JobPlatform
from jobhunter.sources.companies import CompanyBoardsPlatform
from jobhunter.sources.greenhouse import GreenhousePlatform
from jobhunter.sources.hackernews import HackerNewsWhoIsHiringPlatform
from jobhunter.sources.jobspy import LinkedInJobSpyPlatform
from jobhunter.sources.lever import LeverPlatform
from jobhunter.sources.remoteok import RemoteOKPlatform
from jobhunter.sources.remotive import RemotivePlatform
from jobhunter.sources.yc import YCJobsPlatform


@dataclass(frozen=True)
class PlatformSpec:
    name: str
    status: str
    access: str
    notes: str
    factory: Callable[[], JobPlatform] | None = None


PLATFORM_REGISTRY: dict[str, PlatformSpec] = {
    "remotive": PlatformSpec(
        name="remotive",
        status="implemented",
        access="free public JSON API",
        notes="Good first source for remote jobs with structured title, company, location, salary, and description fields.",
        factory=RemotivePlatform,
    ),
    "hackernews": PlatformSpec(
        name="hackernews",
        status="implemented",
        access="free HN Algolia API",
        notes="Useful for Who's Hiring discovery; comments are unstructured and need conservative normalization.",
        factory=HackerNewsWhoIsHiringPlatform,
    ),
    "linkedin": PlatformSpec(
        name="linkedin",
        status="implemented-optional",
        access="python-jobspy scraper adapter",
        notes="Requires Python >=3.10 and optional package python-jobspy. LinkedIn can rate-limit; use responsibly.",
        factory=LinkedInJobSpyPlatform,
    ),
    "a16z": PlatformSpec(
        name="a16z",
        status="implemented",
        access="public Consider JSON endpoint",
        notes="Uses /api-boards/search-jobs (Consider) with jobFunctions=Engineering,Research + cursor pagination to sample ~500 of the board's ~15k jobs across ~770 portfolio companies.",
        factory=A16ZPlatform,
    ),
    "yc": PlatformSpec(
        name="yc",
        status="implemented",
        access="public embedded YC jobs payload",
        notes="Parses the public jobPostings payload embedded on ycombinator.com/jobs.",
        factory=YCJobsPlatform,
    ),
    "companies": PlatformSpec(
        name="companies",
        status="implemented",
        access="direct company career sites (Amazon, Google, Uber APIs + Greenhouse/Lever/Ashby delegates)",
        notes="Deep sweep across 100+ verified company boards by default; configure via JOBHUNTER_COMPANIES or .jobhunter/companies.json. Unsupported sites (meta, tiktok, salesforce, paypal, ...) warn and skip.",
        factory=CompanyBoardsPlatform,
    ),
    "remoteok": PlatformSpec(
        name="remoteok",
        status="implemented",
        access="free public JSON API",
        notes="Global remote board with posting dates, tags, and salary ranges; board fetched once per run and filtered locally.",
        factory=RemoteOKPlatform,
    ),
    "greenhouse": PlatformSpec(
        name="greenhouse",
        status="implemented",
        access="free public Greenhouse board API",
        notes="Direct company boards (AI labs and strong eng brands by default); configure boards via JOBHUNTER_GREENHOUSE_BOARDS.",
        factory=GreenhousePlatform,
    ),
    "lever": PlatformSpec(
        name="lever",
        status="implemented",
        access="free public Lever postings API",
        notes="Direct company boards; configure companies via JOBHUNTER_LEVER_COMPANIES.",
        factory=LeverPlatform,
    ),
    "glassdoor": PlatformSpec(
        name="glassdoor",
        status="planned",
        access="restricted partner/API access",
        notes="Treat as restricted; implement only with permitted API credentials or user-provided exports.",
    ),
    "handshake": PlatformSpec(
        name="handshake",
        status="planned",
        access="institution-authenticated platform",
        notes="Implement only with user-authorized access or exports because data depends on school/account entitlements.",
    ),
}


def build_platforms(names: list[str]) -> list[JobPlatform]:
    platforms: list[JobPlatform] = []
    for name in names:
        spec = PLATFORM_REGISTRY.get(name)
        if spec is None:
            known = ", ".join(sorted(PLATFORM_REGISTRY))
            raise ValueError(f"unknown source '{name}'. Known sources: {known}")
        if spec.factory is None:
            raise NotImplementedError(f"{name} is {spec.status}: {spec.notes}")
        platforms.append(spec.factory())
    return platforms
