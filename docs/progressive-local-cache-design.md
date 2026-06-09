# Progressive Local Job Cache Design

## Motivation

The job agent should not crawl every source upfront. It should build a private local knowledge base over time:

- Each user query triggers a small, targeted fetch.
- Every fetched online item is saved locally.
- Repeated queries reuse local data first, then fetch missing or stale coverage.
- Duplicate postings from the same or different platforms collapse into one normalized job.
- The database runs on the remote Postgres database, but the data is local/private to the the remote Postgres database machine rather than a third-party hosted service.

## Deployment Model

Run the primary relational database on the remote Postgres database:

```text
agent process
  -> postgresql://jobhunter:...@127.0.0.1:5433/jobhunter
  -> local the remote Postgres database disk volume
```

If the agent runs from a laptop, access the same local the remote Postgres database database through an SSH tunnel:

```bash
ssh -N -L 5433:127.0.0.1:5433 -J user@jumphost.example.edu user@db.example.edu
export JOBHUNTER_DATABASE_URL="postgresql://jobhunter:password@127.0.0.1:5433/jobhunter"
```

If the agent runs directly on the remote Postgres database:

```bash
export JOBHUNTER_DATABASE_URL="postgresql://jobhunter:password@127.0.0.1:5433/jobhunter"
```

Use Postgres as the source of truth. Add a graph database only as a projection layer.

## Storage Layers

### 1. Source Query Layer

Records what the agent tried to fetch.

Table: `source_queries`

- `id`
- `source`
- `query_text`
- `normalized_query`
- `role_family`
- `location`
- `filters_json`
- `query_hash`
- `created_at`
- Unique key: `(source, query_hash)`

Purpose:

- Avoid refetching the exact same query too often.
- Track coverage by role family, source, and location.
- Support progressive query expansion.

### 2. Fetch Run Layer

Records each network request or page of results.

Table: `fetch_runs`

- `id`
- `source_query_id`
- `source`
- `request_json`
- `cursor`
- `status`
- `items_seen`
- `items_new`
- `items_updated`
- `error`
- `started_at`
- `finished_at`

Purpose:

- Preserve provenance.
- Retry failed pages.
- Respect source-specific rate limits.
- Know whether a source was queried and returned no data versus never queried.

### 3. Raw Source Item Layer

Stores online source payloads before normalization.

Table: `source_items`

- `id`
- `source`
- `source_item_id`
- `source_url`
- `canonical_url`
- `title`
- `company`
- `location`
- `raw_json`
- `detail_text`
- `detail_content_hash`
- `detail_fetched_at`
- `content_hash`
- `first_seen_at`
- `last_seen_at`
- `seen_count`
- Unique key: `(source, source_item_id)` when source IDs exist.
- Secondary unique key: `(source, canonical_url)` when URLs exist.

Purpose:

- Save all fetched online information, even if it is not a top-ranked match for the current user.
- Save detail-page text progressively when a run has detail budget available.
- Detect source-side content changes by `content_hash`.
- Reprocess old data when the ranking model or normalization improves.

### 4. Normalized Job Layer

Stores deduplicated jobs across platforms.

Table: `jobs`

- `job_key`
- `title`
- `company`
- `canonical_company`
- `url`
- `canonical_url`
- `location`
- `description`
- `tags_json`
- `salary`
- `posted_at`
- `content_hash`
- `first_seen_at`
- `last_seen_at`
- `seen_count`

Deduplication priority:

1. Canonical URL after stripping tracking parameters.
2. Source-specific stable ID.
3. Normalized `(company, title, location)`.
4. Optional future embedding similarity for near-duplicate postings.

Purpose:

- One row per logical job.
- Merge duplicates across LinkedIn, YC, a16z, company ATS boards, and Hacker News.

### 5. Observation Layer

Links raw items and normalized jobs.

Table: `job_observations`

- `id`
- `job_key`
- `source_item_id`
- `fetch_run_id`
- `source`
- `observed_at`
- `source_rank`
- `matched_query_text`
- Unique key: `(job_key, source_item_id, fetch_run_id)`

Purpose:

- Preserve where each job came from.
- Let the agent answer: "Which source found this job?"
- Avoid duplicating job rows while keeping full provenance.

### 6. Search Run Layer

Records user-facing agent runs.

Existing tables can remain:

- `search_runs`
- `job_matches`

But `job_matches` should point to `jobs.job_key`, not raw source records.

Purpose:

- Preserve what the user asked.
- Preserve ranked output, score, rationale, and matched terms.
- Allow comparison across repeated runs.

## Progressive Fetch Algorithm

For each user request:

1. Build a profile and preferences.
2. Generate role-family query tracks, for example:
   - MLE
   - SDE
   - Quant
   - Research Engineer
3. Check local coverage:
   - How many jobs are already cached for each `(source, role_family, location)`?
   - How fresh are they?
   - Which sources have not been queried yet?
4. Rank cached jobs first.
5. If cached coverage is insufficient:
   - fetch only the missing source/query combinations;
   - obey query and per-query result budgets;
   - upsert raw `source_items`;
   - fetch and save bounded detail-page text when requested;
   - normalize and upsert `jobs`;
   - insert `job_observations`;
   - rerank from the combined local + fresh pool.
6. Save the user-facing `search_run` and `job_matches`.
7. Optionally project new jobs into graph storage.

This avoids one giant crawl while still improving the local database every time the agent is used.

## Agentic Recall Budgeting

The recall planner can generate broad tracks for MLE, SDE, quant, research engineering, and LLM infrastructure. This is useful for a 150-job sourcing run, but it must be bounded:

- `--max-queries`: caps generated queries executed in the foreground run.
- `--per-query-limit`: caps jobs requested from each source for each query.
- `--detail-limit`: caps detail pages fetched across the whole run.
- `--detail-timeout`: caps each detail-page request.

Recommended modes:

- Interactive intake smoke: `--max-queries 3 --per-query-limit 3 --detail-limit 2`.
- Normal focused search: `--max-queries 8 --per-query-limit 10 --detail-limit 10`.
- Broad 150-job sourcing: `--max-queries 24 --per-query-limit 20 --detail-limit 25`, preferably as a background run.

Detail pages should accumulate over multiple runs. The platform should not try to fetch every details page in one user-facing invocation.

## Freshness Policy

Recommended defaults:

- LinkedIn: refresh query after 12-24 hours.
- YC/a16z: refresh after 24 hours.
- Remotive: refresh after 12 hours.
- Hacker News Who's Hiring: refresh current monthly thread after 6-12 hours.
- Official company pages: refresh after 24-72 hours.

Stale cached jobs are still usable for ranking, but fresh fetches should be preferred for final output.

## Graph Projection

Graph storage should be a projection, not the source of truth.

Nodes:

- `CandidateProfile`
- `SearchRun`
- `SourceQuery`
- `Job`
- `Company`
- `Skill`
- `Source`

Edges:

- `(SearchRun)-[:USED_QUERY]->(SourceQuery)`
- `(SourceQuery)-[:FETCHED]->(Job)`
- `(CandidateProfile)-[:MATCHED {score, rank, run_id}]->(Job)`
- `(Job)-[:AT_COMPANY]->(Company)`
- `(Job)-[:FROM_SOURCE]->(Source)`
- `(Job)-[:MENTIONS_SKILL]->(Skill)`
- `(CandidateProfile)-[:HAS_SKILL]->(Skill)`

Use the same `job_key` from Postgres for graph `Job` nodes.

## the remote Postgres database Setup Recommendation

Use local Postgres on the remote Postgres database. If Docker is available:

```yaml
services:
  jobhunter-postgres:
    image: pgvector/pgvector:pg16
    container_name: jobhunter-postgres
    restart: unless-stopped
    ports:
      - "127.0.0.1:5433:5432"
    environment:
      POSTGRES_DB: jobhunter
      POSTGRES_USER: jobhunter
      POSTGRES_PASSWORD: change-me
    volumes:
      - ./postgres-data:/var/lib/postgresql/data
```

If Docker is not available, install Postgres in a user-managed environment and bind it to `127.0.0.1` only.

Optional graph stores:

- Neo4j local container for graph projection.
- Apache AGE extension inside Postgres if a single-process setup is preferred.
- Kuzu for embedded local graph experiments.

## Implemented MVP

Implemented in the current codebase:

- `source_queries`
- `fetch_runs`
- `source_items`
- `source_items.detail_text`
- `job_observations`
- `ProgressiveJobCache`
- CLI flag: `--progressive-cache`
- CLI flag: `--agentic-search`
- CLI flag: `--max-queries`
- CLI flag: `--per-query-limit`
- CLI flag: `--fetch-details`
- CLI flag: `--detail-limit`
- CLI flag: `--detail-timeout`

The agent should call:

```python
cache.search_or_fetch(profile, preferences, sources, desired_count)
```

Instead of:

```python
platform.search(query, profile)
```

directly for every run.

The cache layer decides whether to reuse local data, fetch fresh data, or both.

CLI usage with a the remote Postgres database-local Postgres tunnel:

```bash
ssh -N -L 5433:127.0.0.1:5433 -J user@jumphost.example.edu user@db.example.edu
export JOBHUNTER_DATABASE_URL="postgresql://jobhunter:password@127.0.0.1:5433/jobhunter"

python -m jobhunter \
  --input /path/to/resume.md \
  --sources yc,a16z,linkedin,remotive,hackernews \
  --progressive-cache \
  --agentic-search \
  --max-queries 24 \
  --per-query-limit 20 \
  --fetch-details \
  --detail-limit 25 \
  --set-preference result_count=150 \
  --set-preference output_format=tsv
```

Development smoke test with SQLite:

```bash
python -m jobhunter \
  --input "Machine Learning Engineer with Python LLM. Remote US." \
  --offline \
  --progressive-cache \
  --store-db /tmp/jobhunter-cache.sqlite \
  --limit 2
```

MVP limitations:

- Freshness is source/query based with a default 24-hour TTL.
- Cached ranking uses the current in-process scorer; there is not yet a separate retrieval index.
- Postgres schema is created automatically; the remote Postgres database access requires an SSH tunnel or running the agent directly on the remote Postgres database.
- Broad 150-job sourcing has a first agentic query-track planner, but ranking still needs stricter role-fit gates for noisy resume keywords.
