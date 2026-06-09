# Jobhunter Demo Design

## Goal

Create a coding-agent skill ecosystem that can take candidate material, build a structured profile, search multiple job platforms through a common interface, and rank opportunities with explainable matching.

## Layers

1. Input layer
   - `load_input` accepts raw text, local files, regular URLs, and GitHub profile URLs.
   - GitHub profile URLs use the public GitHub user API first, then fall back to HTML text extraction.

2. Profile layer
   - `build_user_profile` extracts name, headline, roles, skills, locations, seniority, links, and search keywords.
   - `JobPreferences` stores user-stated preferences such as target roles, preferred locations, remote preference, company stage, industries, minimum salary, visa sponsorship, preferred sources, and excluded terms.
   - `adaptive_preference_questions` generates missing-preference questions from the current profile and existing answers.
   - Preferences can be saved to JSON and reloaded across runs.
   - The current implementation is heuristic and explainable. A later version can replace or augment it with an LLM profile normalizer while preserving the `UserProfile` contract.

3. Platform layer
   - `JobPlatform` defines the adapter interface.
   - Implemented adapters: Remotive, Hacker News Who's Hiring, a16z portfolio jobs, YC startup jobs, and optional JobSpy-backed LinkedIn.
   - Planned/restricted adapters are registered for Glassdoor and Handshake.

4. Agentic search layer
   - `QueryPlanner` writes role/skill/location queries from the profile.
   - `JobSearchAgent` runs those queries across sources, deduplicates records, filters obvious location/core-fit mismatches, and ranks results.
   - `JobMatch` stores score, matched terms, query, and rationale so results are auditable.

## First Demo Source Choice

Remotive is the first live source because it exposes a free JSON endpoint with normalized job fields. Hacker News is included as a second free source, but its data is discussion text, so ranking should remain conservative.

LinkedIn is integrated through JobSpy as an optional adapter. JobSpy requires Python 3.10+ and can be rate-limited by LinkedIn, so the CLI keeps limits modest and lazy-loads the dependency only when `--sources linkedin` is selected.

a16z is integrated through the public Consider endpoint used by `jobs.a16z.com`: `POST /api-boards/search-jobs` with board id `andreessen-horowitz`. YC is integrated through the `data-page` JSON payload embedded on `https://www.ycombinator.com/jobs`.

## Next Steps

- Add persistent search sessions so the agent can refine queries over time.
- Add a richer resume parser for PDF/DOCX inputs.
- Add application tracking, cover-letter drafts, and outreach notes.
- Add optional LLM profile extraction and query rewriting behind the same data contracts.
