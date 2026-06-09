# Job Search Storage Design

## Goals

- Persist every search run so the agent can compare runs over time.
- Store each unique job posting once, even if repeated queries or sources return it again.
- Preserve run-specific ranking, matched terms, query text, and rationale.
- Keep a the remote Postgres database-local relational database path for reliable history and a graph database path for relationship-heavy analysis.

## Production Relational Store

Production storage should run on the remote Postgres database but keep data local/private to that machine. Configure a Postgres-compatible database on the remote Postgres database and point the agent at it:

```bash
export JOBHUNTER_DATABASE_URL="postgresql://jobhunter:password@127.0.0.1:5433/jobhunter"

python -m jobhunter \
  --input examples/resume.md \
  --sources remotive,hackernews \
  --limit 10
```

The CLI also accepts an explicit URL:

```bash
python -m jobhunter \
  --input examples/resume.md \
  --sources a16z,yc,hackernews \
  --limit 10 \
  --store-url "$JOBHUNTER_DATABASE_URL"
```

If the agent runs from a laptop, use an SSH tunnel to the the remote Postgres database-local database:

```bash
ssh -N -L 5433:127.0.0.1:5433 -J user@jumphost.example.edu user@db.example.edu
export JOBHUNTER_DATABASE_URL="postgresql://jobhunter:password@127.0.0.1:5433/jobhunter"
```

SQLite remains available only for quick development and tests through `--store-db`.

For progressive source caching, use the fuller design in `docs/progressive-local-cache-design.md`.

Tables:

- `jobs`
  - One row per deduplicated posting.
  - Primary key: `job_key`.
  - Stores normalized posting fields, raw source payload, content hash, `first_seen_at`, `last_seen_at`, and `seen_count`.
- `search_runs`
  - One row per CLI/agent search execution.
  - Stores input reference, full profile JSON, preferences, sources, source errors, and timestamp.
- `job_matches`
  - Join table between a search run and a job.
  - Stores rank, score, matched terms, generated query, and rationale.

Deduplication:

1. Prefer canonical URL when available.
2. Strip tracking parameters such as `utm_*`, `gh_src`, and `source`.
3. Fall back to `(source, source_id)` when URL is not usable.
4. Fall back to normalized `(company, title, location)` only when necessary.

This means repeated runs update `jobs.last_seen_at` and increment `jobs.seen_count`, while each run still keeps its own `job_matches` rows.

Development-only local usage:

```bash
python -m jobhunter \
  --input examples/resume.md \
  --sources remotive,hackernews \
  --limit 10 \
  --store-db .jobhunter/jobs.sqlite
```

## Graph Store

The graph database should not replace the relational store. It should be a projection optimized for relationship queries, populated from the same saved search-run and source-cache events.

Recommended nodes:

- `CandidateProfile`
  - Stable candidate identity or input fingerprint.
- `SearchRun`
  - One node per run.
- `SearchQuery`
  - Generated query text and filters.
- `Job`
  - Same `job_key` as relational `jobs`.
- `Company`
  - Canonical company name/domain.
- `Skill`
  - Normalized skill or salient portfolio highlight.
- `Source`
  - Platform adapter name such as `hackernews`, `a16z`, `yc`, `linkedin`.

Recommended edges:

- `(CandidateProfile)-[:USED_IN]->(SearchRun)`
- `(SearchRun)-[:EMITTED]->(SearchQuery)`
- `(SearchQuery)-[:RETURNED {score, rank, rationale}]->(Job)`
- `(Job)-[:AT_COMPANY]->(Company)`
- `(Job)-[:FROM_SOURCE]->(Source)`
- `(Job)-[:MENTIONS_SKILL]->(Skill)`
- `(CandidateProfile)-[:HAS_SKILL]->(Skill)`
- `(CandidateProfile)-[:MATCHED {score, rank, run_id}]->(Job)`

Graph dedupe:

- Use the same `job_key` as the relational store for `Job`.
- Use normalized lowercase skill names for `Skill`.
- Use canonical company name/domain for `Company`.
- Store edge properties per run, rather than duplicating job nodes.

Recommended write path:

- Write fetched source items and the search run to the the remote Postgres database-local relational store first.
- Emit the saved run and job keys to a graph projection worker.
- Upsert graph nodes by stable keys.
- Store per-run match evidence as edge properties.
- If graph writes fail, retry from relational search-run history instead of losing raw results.

Useful graph queries:

- Jobs repeatedly matched across runs.
- Companies that match several candidate skills.
- Skill gaps between candidate highlights and high-scoring jobs.
- Which sources produce the strongest matches for a given role family.
- Career trajectory recommendations based on connected skills, publications, projects, and job requirements.

## Extension Points

Future storage adapters should share the same contract:

```python
save_search_run(input_ref, profile, sources, matches, source_errors) -> StoreSummary
```

Recommended adapters:

- `PostgresJobStore`: the remote Postgres database/production relational store.
- `SQLiteJobStore`: local development and tests only.
- `Neo4jJobGraphStore`: graph projection.
- `CompositeJobStore`: write to relational and graph stores in one call.
