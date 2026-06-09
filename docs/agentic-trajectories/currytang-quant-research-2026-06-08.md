# CurryTang Quant Research Search Trajectory

Date: 2026-06-08

## Objective

Use the `job-hunting` skill to search for quantitative researcher jobs from the GitHub portfolio at https://github.com/CurryTang, then debug and improve the workflow.

## 1. Portfolio Analysis

Input:

```text
https://github.com/CurryTang
```

Command:

```bash
python -m jobhunter --input https://github.com/CurryTang --sources remotive,a16z,yc --limit 20 --json
```

Extracted profile:

- Name: Zhikai Chen
- Location evidence: Michigan State University, East Lansing, United States
- Corrected inferred roles after reading the profile README: research scientist, machine learning engineer, software engineer, research engineer
- Corrected inferred skills after reading the profile README: research, DL infra, long-context modeling, agentic memory, memory systems, proactive agents, LLM, GPU tooling, optimization, relational deep learning, relational in-context learning, relational foundation models, tabular data, machine learning, Python, graph learning
- Portfolio evidence:
  - GitHub self-introduction: current CS PhD student at Michigan State University.
  - Current section: `DL Infra, Agent, Long Context Modeling (2026-present)`.
  - Current 2026 publications: agentic memory systems; proactive agents and LLM-based wake/anchor decisions.
  - Current projects: `Amadeus` AI research assistant; `slack-gpu-monitor` GPU/server management bot.
  - Current writing: DL infra tutorial and optimization notes.
  - Recent research area: relational deep learning / relational foundation models / relational in-context learning, including OpenRFM, RFMBench, AutoG, Relatron.
  - Older graph section: graph foundation model and TAG/LLM work from 2023-2025, but the README explicitly says these libraries are not maintained anymore and should not be the main focus.

Positioning:

```text
ML/LLM research candidate for quantitative research and quant research engineering,
especially roles involving agentic research systems, long-context/agent memory,
large-scale ML research infrastructure, relational/tabular modeling, forecasting,
optimization, alpha modeling, nonstationary data, and Python-heavy experimentation.
```

Assumed preferences for the first search:

- Target roles: quantitative researcher, quant researcher, machine learning researcher, research scientist
- Locations: New York, Chicago, San Francisco, Remote US
- Industries: quant finance, financial technology, AI
- Remote: true

## 2. Agentic Search Attempts

Live structured-source command:

```bash
python -m jobhunter \
  --input https://github.com/CurryTang \
  --sources remotive,a16z,yc,hackernews \
  --limit 30 \
  --json \
  --set-preference target_roles="quantitative researcher,quant researcher,machine learning researcher,research scientist" \
  --set-preference preferred_locations="New York,Chicago,San Francisco,Remote US" \
  --set-preference industries="quant finance,financial technology,AI" \
  --set-preference remote=true
```

Result quality:

- The agent found AI/startup roles from Hacker News, YC, and a16z.
- Top matches were mostly `python llm` or applied AI roles, not true quant research.
- The source set is good for startup discovery but weak for finance-specific quant roles.

LinkedIn attempt:

```bash
python -m jobhunter \
  --input https://github.com/CurryTang \
  --sources linkedin \
  --limit 20 \
  --json \
  --set-preference target_roles="quantitative researcher,quant researcher,machine learning researcher,research scientist" \
  --set-preference preferred_locations="New York,Chicago,San Francisco,Remote US" \
  --set-preference industries="quant finance,financial technology,AI" \
  --set-preference remote=true
```

Result:

- No LinkedIn results were returned because optional `python-jobspy` was not installed.
- The agent correctly recorded source warnings.

Manual/current web search used to fill the finance-specific source gap:

- Jane Street Machine Learning Researcher, NYC
  - https://www.janestreet.com/join-jane-street/position/4276720002/
- Two Sigma Quantitative Researcher: Machine Learning, New York
  - https://careers.twosigma.com/careers/JobDetail/New-York-New-York-United-States-Quantitative-Researcher-Machine-Learning/12634
- Jane Street Quantitative Researcher, NYC
  - https://www.janestreet.com/join-jane-street/position/6302325002/
- Citadel Quantitative Researcher, PhD Graduate, New York/Miami
  - https://www.citadel.com/careers/details/quantitative-researcher-phd-graduate-us/
- Citadel Quantitative Research Engineer, PhD Graduate, New York/Miami
  - https://www.citadel.com/careers/details/quantitative-research-engineer-phd-graduate-us/
- Point72 Quantitative Researcher / Machine Learning, New York
  - https://careers.point72.com/?location=new+york
- DRW Quantitative Researcher, Chicago
  - https://www.drw.com/work-at-drw/listings/quantitative-researcher-3173309
- Optiver Quantitative Research and Machine Learning roles
  - https://www.optiver.com/join-us/jobs/quantitative-research-and-machine-learning/
- Hudson River Trading Quantitative Researcher, Mid-Freq, New York
  - https://www.hudsonrivertrading.com/hrt-job/quantitative-researcher-mid-freq/

## 3. Debug Notes

Observed failure modes:

- Initial GitHub ingestion did not read the profile README/self-introduction, so it missed the user's current positioning.
- Initial GitHub ingestion treated repo descriptions flatly and over-weighted older graph projects.
- Query planning used `target_roles`, but did not expand quant-specific synonyms such as alpha research, systematic trading, statistical arbitrage, time-series, and signal research.
- Ranking mostly weighted profile roles and skills; target role preferences were underweighted.
- Broad skill-pair queries such as `python llm` produced many applied AI roles that were technically related but not quant research.
- The implemented source set lacked finance-specific boards, so manual official-career-site search was needed.
- LinkedIn coverage requires optional `python-jobspy`.

Fix direction:

- Add a generic portfolio-salience extraction layer instead of hard-coding a specific profile's prompt or project list.
- Use structure and evidence signals: current/recent sections, section order, publications, projects, impact venues, systems built, and deprecation/past-work language.
- Use extracted highlights to drive roles, skills, and keywords before flat repository metadata.
- Expand quant-finance roles and industry terms during query planning.
- Treat user target roles as first-class ranking terms.
- Add domain bonuses for quant-finance evidence when the user asks for quant roles.
- Penalize non-quant results when quant target roles are explicit and the posting lacks finance/quant evidence.
- Preserve broad ML/AI results as fallbacks, but rank them below direct quant matches.

## 4. Improvement Loop

Patch goals:

- Add quant-domain query expansion.
- Improve role-preference weighting.
- Add regression tests that a quant ML role outranks a generic LLM software role for this target.
- Keep existing startup and offline demos working.

Implemented changes:

- `jobhunter/agent.py`
  - Added quant-role terms and quant-domain terms.
  - Added quant-specific generated queries such as `quantitative researcher machine learning python`, `quant research engineer python machine learning`, and `alpha research machine learning python`.
  - Weighted `profile.preferences.target_roles` as first-class ranking terms.
  - Added a quant-domain evidence bonus.
  - Added a stricter core-match gate for explicit quant searches so generic AI roles are filtered unless they contain direct quant/finance evidence or direct target-role evidence.
  - Fixed a location bug where `Remote US` in the preference list caused a `New York` posting to be filtered out.
  - Fixed quant planning to use the full profile skill set so Python/ML/LLM remain available even when recent self-introduction terms occupy the first skill slots.
- `jobhunter/profile.py`
  - Added GitHub profile README/self-introduction loading from `CurryTang/CurryTang`.
  - Changed repo metadata ordering to `sort=pushed` to better reflect recent projects.
  - Added a generic portfolio highlight extractor that scores lines using current/recent section signals, ordered sections, publication/venue signals, project/system-building signals, ownership/impact signals, and stale/deprecated-work penalties.
  - Added extracted highlights to profile evidence and used highlight keywords before flat-document keywords.
  - Added phrase normalization so `long-context` and `long context` match the same concept.
  - Added keyword cleanup for author names, repository metadata, timestamp fragments, and generic publication boilerplate.
  - Added general vocabulary for DL infra, long context, agentic memory, memory systems, proactive agents, GPU tooling, optimization, relational deep learning, relational foundation models, relational in-context learning, and tabular data.
  - Added role inference for research scientist when current research signals appear.
- `tests/test_agent.py`
  - Added quant query expansion coverage.
  - Added a regression test that a direct quant ML role survives while a generic LLM role is filtered for explicit quant searches.
  - Added a regression test for named-city matching when `Remote US` is also in preferences.
- `tests/test_profile.py`
  - Added coverage proving GitHub profile README content is included and current self-introduction signals are extracted.
  - Added coverage proving current/recent highlights outrank stale/deprecated sections.

Verification:

```bash
python - <<'PY'
import importlib
import inspect
import pathlib
import sys

failures = []
for path in sorted(pathlib.Path('tests').glob('test_*.py')):
    module = importlib.import_module(f"tests.{path.stem}")
    for name, func in sorted(vars(module).items()):
        if name.startswith('test_') and callable(func):
            sig = inspect.signature(func)
            if sig.parameters:
                continue
            try:
                func()
            except Exception as exc:
                failures.append((f'{path}:{name}', exc))

if failures:
    for test, exc in failures:
        print(f'FAIL {test}: {exc!r}')
    sys.exit(1)
print('PASS import-based tests')
PY
```

Result:

```text
PASS import-based tests
```

Note: local `pytest` is wrapped by RTK on this machine and its terminal output reported `Pytest: No tests collected`; the import-based harness was used to verify the pure test functions directly.

Final live search command:

```bash
python -m jobhunter \
  --input https://github.com/CurryTang \
  --sources remotive,a16z,yc,hackernews \
  --limit 10 \
  --set-preference target_roles="quantitative researcher,quant researcher,machine learning researcher,research scientist" \
  --set-preference preferred_locations="New York,Chicago,San Francisco,Remote US" \
  --set-preference industries="quant finance,financial technology,AI" \
  --set-preference remote=true
```

Top improved structured-source matches after generic salience extraction:

1. Nof1 - Research Engineer / Full-Stack Engineer / Infrastructure Engineer
   - Source: Hacker News Who's Hiring
   - URL: https://news.ycombinator.com/item?id=48363998
   - Why: AI research lab applying AI to trading and forecasting; mentions Alpha Arena, financial markets, backtesting, simulation, quantitative trading, machine learning, Python.
2. Quin - Founding Engineer
   - Source: Hacker News Who's Hiring
   - URL: https://news.ycombinator.com/item?id=48441385
   - Why: finance-adjacent agentic product, backend/data layer, Python/FastAPI, LLM inference; not pure quant research but closer than generic AI roles.
3. Catalyst Wayfare AI - Lead AI Engineer + Agent Builder + Platform Engineer
   - Source: Hacker News Who's Hiring
   - URL: https://news.ycombinator.com/item?id=48385146
   - Why: production AI systems in regulated domains including finance, with LLM/agentic systems and Python.
4. BIT Capital - Head of Engineering
   - Source: Hacker News Who's Hiring
   - URL: https://news.ycombinator.com/item?id=48357777
   - Why: investment/markets company, alpha evidence, Python/LLM/agentic tooling; likely too senior, but relevant to quant-finance infrastructure.

Corrected profile output:

```text
headline: Research Scientist
roles: research scientist, machine learning engineer, software engineer, research engineer
skills: research, dl infra, long context modeling, long context, agentic memory, agentic, memory systems, proactive agents, agents, llm
```

This is intentionally stricter than the earlier run: broad finance-adjacent startup roles were filtered out because the user asked for quantitative researcher jobs, not generic applied-AI engineering.

Remaining gap:

- The built-in sources still do not cover official quant-finance career pages. The best direct quant-research targets remain official roles at Jane Street, Two Sigma, Citadel, Point72, DRW, Optiver, and HRT, which should become a dedicated `JobPlatform` adapter or curated official-board search module in the next iteration.

## 5. Storage and Intake Follow-up

User feedback:

- Do not store production query results locally.
- Store results on the remote Postgres database using a more scalable database.
- Do not insert duplicate jobs across repeated queries.
- Make the skill ask clarifying questions like a guided intake flow before search.

Implemented storage changes:

- Added remote-first storage through `--store-url` and `JOBHUNTER_DATABASE_URL`.
- Added `PostgresJobStore` for a Postgres-compatible the remote Postgres database production database.
- Kept `SQLiteJobStore` only for development and tests.
- Added `create_job_store(url)` so production URLs such as `postgresql://...` route to the remote adapter.
- Added optional dependency group: `python -m pip install -U ".[postgres]"`.
- Added production schema creation for:
  - `jobs`
  - `search_runs`
  - `job_matches`
- Preserved deterministic job dedupe:
  - Prefer canonical URL.
  - Strip tracking params such as `utm_*`, `gh_src`, and `source`.
  - Fall back to `(source, source_id)`.
  - Fall back to normalized `(company, title, location)` only when necessary.
- Repeated runs update `jobs.last_seen_at` and increment `jobs.seen_count`; each run still records its own ranked `job_matches`.

Recommended production command:

```bash
export JOBHUNTER_DATABASE_URL="postgresql://user:password@db.example.com:5432/jobhunter"

python -m jobhunter \
  --input resume.md \
  --sources remotive,a16z,yc,hackernews \
  --limit 10
```

Graph database design:

- Treat the remote relational store as the source of truth.
- Build graph storage as a projection from saved search-run events.
- Use stable keys:
  - `Job.job_key`
  - normalized skill name
  - canonical company name/domain
  - saved `SearchRun.id`
- If graph writes fail, replay from relational history instead of losing source results.

Implemented intake changes:

- Added `JobPreferences.focus_highlights`.
- `adaptive_preference_questions(profile)` now asks about portfolio focus first when multiple high-signal highlights exist.
- Query planning uses selected focus highlights as high-priority query terms.
- Ranking gives selected focus highlights extra weight.
- Updated both repository and active global `job-hunting` skill instructions to ask:
  - portfolio highlights to emphasize
  - target role tracks
  - preferred locations and remote/hybrid/onsite
  - industries, stages, job types, salary floor, and visa needs

Simulated intake command:

```bash
python -m jobhunter \
  --input https://github.com/CurryTang \
  --offline \
  --show-questions \
  --limit 3
```

Observed question flow:

```text
focus_highlights: Which portfolio strengths should I emphasize most?
target_roles: Which roles should I prioritize?
preferred_locations: Where do you want to work?
remote: Are remote roles acceptable or preferred?
company_stages: What company stages do you prefer?
```

Simulated answered live search:

```bash
python -m jobhunter \
  --input https://github.com/CurryTang \
  --sources remotive,a16z,yc,hackernews \
  --limit 5 \
  --set-preference focus_highlights="agentic memory,long context modeling,proactive agents" \
  --set-preference target_roles="quantitative researcher,machine learning researcher,research scientist" \
  --set-preference preferred_locations="New York,Chicago,San Francisco,Remote US" \
  --set-preference industries="quant finance,financial technology,AI" \
  --set-preference remote=true
```

Observed ranked results:

1. Nof1 - Research Engineer / Full-Stack Engineer / Infrastructure Engineer
   - Source: Hacker News Who's Hiring
   - Why: AI research lab applying AI to trading; matched agentic/research/Python/quant/trading evidence.
2. Karat Financial - Product Engineer, Karat Platform
   - Source: YC
   - Why: finance evidence but weaker role fit than Nof1.

Verification after these changes:

```text
25 import-based tests passed.
py_compile passed for jobhunter modules.
create_job_store("postgresql://...") returns PostgresJobStore.
```

Not yet verified:

- A real the remote Postgres database insert was not attempted because no live `JOBHUNTER_DATABASE_URL` credentials were provided.

## 6. User-Answered Intake and Search

User answers:

```text
1. Focus highlights: A, B, C, D
   - Agentic memory systems / long-context agent memory
   - Proactive agents / autonomous agent decision-making
   - Relational foundation models / relational in-context learning
   - Tabular/relational data modeling, AutoG, RFMBench, Relatron
2. Role priority: A > B > C > D > E
   - Quantitative Researcher
   - ML Researcher / Research Scientist
   - Quant Research Engineer
   - ML Engineer / Research Engineer
   - AI Agent / LLM Infrastructure roles
3. Location: New York
4. Remote/location mode: interpreted as all acceptable; New York remains priority.
5. Industries: quant, AI labs, startup
```

Structured-source command:

```bash
python -m jobhunter \
  --input https://github.com/CurryTang \
  --sources remotive,a16z,yc,hackernews \
  --limit 10 \
  --set-preference focus_highlights="agentic memory systems,long-context agent memory,proactive agents,relational foundation models,relational in-context learning,tabular relational data modeling,AutoG,RFMBench,Relatron" \
  --set-preference target_roles="quantitative researcher,machine learning researcher,quant research engineer,research engineer,ml engineer,llm infrastructure" \
  --set-preference preferred_locations="New York" \
  --set-preference industries="quant,AI labs,startup,trading"
```

Structured-source result:

1. Nof1 - Research Engineer / Full-Stack Engineer / Infrastructure Engineer
   - Source: Hacker News Who's Hiring
   - URL: https://news.ycombinator.com/item?id=48363998
   - Why: AI research lab applying AI to trading; matched research engineer, agentic, machine learning, research, Python, quantitative, alpha, and trading.

Storage status:

```text
JOBHUNTER_DATABASE_URL set: False
```

No production storage write was attempted because the the remote Postgres database connection URL was not configured.

Official career-page search found stronger direct targets:

- Jane Street - Machine Learning Researcher, NYC
  - https://www.janestreet.com/join-jane-street/position/8576928002/
- Jane Street - Quantitative Researcher, NYC
  - https://www.janestreet.com/join-jane-street/position/6302325002/
- Two Sigma - Quantitative Researcher: Machine Learning, New York
  - https://careers.twosigma.com/careers/JobDetail/New-York-New-York-United-States-Quantitative-Researcher-Machine-Learning/12634
- Citadel - Quantitative Researcher, PhD Graduate, New York/Miami
  - https://www.citadel.com/careers/details/quantitative-researcher-phd-graduate-us/
- Citadel - Quantitative Researcher, Data Strategies Group, New York
  - https://www.citadel.com/careers/details/quantitative-researcher-data-strategies-group/
- Point72 / Cubist - Quantitative Researcher, Machine Learning, New York
  - https://careers.point72.com/CSJobDetail?jobCode=CSS-0013280&jobName=quantitative-researcher-machine-learning
- Point72 / Cubist IAC - Quantitative Researcher, Machine Learning, New York/London/Hong Kong
  - https://careers.point72.com/CSJobDetail?jobCode=CSS-0013392&jobName=quantitative-researcher-machine-learning
- Optiver - Quantitative Researcher, HFT Futures/Equities, New York
  - https://optiver.com/working-at-optiver/career-opportunities/8440642002/
- Optiver - Graduate Quantitative Researcher, PhD 2026 Start, New York
  - https://optiver.com/working-at-optiver/career-opportunities/8053587002
- DRW - Quantitative Researcher, Chicago
  - https://www.drw.com/work-at-drw/listings/quantitative-researcher-3173309
- Anthropic - Research Scientist/Engineer, Honesty, New York/San Francisco
  - https://www.anthropic.com/careers/jobs/4532887008
- OpenAI careers search showed several agent/research roles, mostly San Francisco, plus NYC non-research roles.
  - https://openai.com/careers/search
- Google DeepMind careers include Research Scientist / Research Engineer tracks and New York City as a location.
  - https://deepmind.google/about/careers/

## 7. Result Count and Output Format Intake

User feedback:

- The skill should also ask how many jobs the user wants.
- The skill should ask the desired output format.
- Default output format should be TSV.

Implemented changes:

- Added `JobPreferences.result_count`.
- Added `JobPreferences.output_format`.
- `adaptive_preference_questions()` now asks:
  - `result_count`: how many jobs to return.
  - `output_format`: TSV, JSON, or Markdown; TSV is default.
- Increased default adaptive question limit from 5 to 8 so these questions are visible in the first intake pass.
- CLI result limit now uses `preferences.result_count` when provided.
- CLI default search output is TSV when `--json` and `output_format` are not set.
- `--show-questions` remains human-readable for intake.
- Updated active global skill instructions to require result count and output format questions.

Verification:

```text
27 import-based tests passed.
py_compile passed for jobhunter modules.
Default CLI search output starts with:
rank    score   title   company source  location salary  url matched_terms   rationale
```

## 8. Resume-Based 150-Job Full Test

User request:

- Use the user's resume.
- Return 150 jobs.
- Cover MLE, SDE, and quant.
- Ensure multiple platforms are queried, including YC, a16z, LinkedIn, and others.

Resume input:

```text
/path/to/resume.pdf
```

Preparation:

```bash
pdftotext /path/to/resume.pdf /tmp/currytang_resume.txt
```

LinkedIn dependency:

- Default `python` is Python 3.9.13.
- `python-jobspy` requires Python 3.10+.
- Installed and ran the LinkedIn test with `/opt/homebrew/bin/python3.11`.

First full-agent run:

- Sources: YC, a16z, LinkedIn, Remotive, Hacker News.
- Requested count: 150.
- Returned count: 59.
- Source coverage:
  - Hacker News: 1
  - LinkedIn: 35
  - Remotive: 9
  - a16z: 8
  - YC: 6
- Role coverage:
  - MLE: 21
  - SDE: 26
  - Quant: 15

Debug finding:

- The default agent query plan is too narrow for a 150-job broad sourcing run.
- Resume-derived location signals such as Michigan / East Lansing / USA can over-filter jobs whose source location format is `New York, NY`, `San Francisco, CA`, etc.
- LinkedIn works under Python 3.11, but it should be configured with a wider `results_wanted` and relaxed `hours_old` for broad sourcing.

Expanded sweep:

- Used extracted resume text as profile input.
- Cleared inferred location hard filters for this broad sourcing test.
- Queried four high-recall role tracks:
  - MLE / LLM / Python
  - SDE / backend / infrastructure
  - Quant researcher / ML / trading
  - Research engineer / LLM infrastructure / agents
- Platforms queried:
  - YC
  - a16z
  - LinkedIn via JobSpy
  - Remotive
  - Hacker News Who's Hiring

Output:

```text
./docs/search-results/currytang-resume-150-2026-06-08.tsv
```

Verification:

```text
151 lines total: 1 TSV header + 150 job rows.
```

Raw source counts:

```text
YC: 80
a16z: 200
LinkedIn: 350
Remotive: 112
Hacker News: 11
```

Final deduplicated top-150 source counts:

```text
LinkedIn: 110
Remotive: 15
a16z: 11
Hacker News: 8
YC: 6
```

Final role coverage counts:

```text
MLE-like: 64
SDE-like: 63
Quant-like: 49
```

Top examples:

1. Factory AI - AI/Fullstack/Platform/Data/Product Engineers
2. Nof1 - Research Engineer / Infrastructure Engineer, AI lab applying AI to trading
3. OpenAI - Software Engineer, Cloud Agents
4. Tetsuwan Scientific - Software Engineer
5. ByteDance - Research Scientist, Data Management / LLM / AI Agents
6. Glean - Machine Learning Engineer, LLM Evals & Observability
7. Quanta Search - Quantitative Researcher for US Equities Market Making
8. DRW - Quantitative Researcher - Machine Learning

Remaining product gap:

- The CLI's default `JobSearchAgent` is conservative and did not reach 150 by itself.
- For future production use, add a first-class broad sourcing mode that:
  - expands query tracks by role family,
  - runs LinkedIn with Python 3.10+ and wider result caps,
  - relaxes resume-inferred location filters unless the user explicitly sets location,
  - then ranks and deduplicates into TSV.

## 9. the remote Postgres database Progressive Local Cache Design

User clarification:

- Configure the database on the remote Postgres database.
- Keep data local/private to the remote Postgres database rather than relying on an external hosted database.
- The motivation is to progressively save online job information as the agent queries, not to crawl the whole web once upfront.

Design outcome:

- Added `docs/progressive-local-cache-design.md`.
- Updated `docs/storage-design.md` from "remote-first" wording to "the remote Postgres database-local/private Postgres".

## 10. the remote Postgres database Postgres and Graph Setup

Actual the remote Postgres database deployment:

```text
host: db.example.edu via jumphost.example.edu
postgres env: /home/user/jobhunter-platform/pg-env
postgres data: /home/user/jobhunter-platform/postgres-data
postgres log: /home/user/jobhunter-platform/postgres.log
postgres bind: 127.0.0.1:5433
database/user: jobhunter / jobhunter
env file: /home/user/jobhunter-platform/.env
kuzu env: /home/user/jobhunter-platform/graph-env
kuzu db: /home/user/jobhunter-platform/kuzu-jobhunter.db
```

Why this shape:

- Docker was present but not usable without sudo access to `/var/run/docker.sock`.
- Postgres 16 was installed in a user-managed conda environment instead.
- Kuzu was chosen for the first graph projection because it is embedded and does not need Docker or a daemon.

Verified remote services:

```text
pg_isready on remote-postgres 127.0.0.1:5433: accepting connections
psql current_database/current_user: jobhunter | jobhunter
Kuzu smoke query: Job(smoke-job)-[:MENTIONS]->Skill(python)
```

## 11. Progressive Cache, Detail Storage, and Dedupe Improvements

Implemented changes:

- Added source-cache tables to SQLite and Postgres:
  - `source_queries`
  - `fetch_runs`
  - `source_items`
  - `job_observations`
- Added detail-page storage to `source_items`:
  - `detail_text`
  - `detail_content_hash`
  - `detail_fetched_at`
- Added `ProgressiveJobCache`, which:
  - checks source/query freshness before fetching;
  - saves raw source items and normalized jobs;
  - saves observation provenance for each source item;
  - reranks from cached plus newly fetched jobs.
- Improved cross-platform dedupe key:
  - first use logical identity `(normalized company, normalized title, normalized location)`;
  - then canonical URL;
  - then source-specific ID;
  - then a content fallback.
- Added bounded agentic recall controls:
  - `--agentic-search`
  - `--max-queries`
  - `--per-query-limit`
  - `--fetch-details`
  - `--detail-limit`
  - `--detail-timeout`
- Added optional Kuzu graph projection:
  - `CandidateProfile`
  - `Job`
  - `Company`
  - `Skill`
  - `HAS_SKILL`, `MENTIONS`, `AT_COMPANY`, `MATCHED`

Why query/detail budgets matter:

- A 24-query agentic plan across multiple sources is correct for broad recall, but it should run as a bounded/background retrieval job.
- Interactive smoke tests and skill invocations need query budgets, otherwise a single slow platform can dominate wall time.
- Detail pages should accumulate progressively. The agent should not fetch every detail page for every generated query in one foreground run.

Verification:

```text
35 import-based tests passed.
py_compile passed for jobhunter modules.
```

the remote Postgres database offline progressive smoke:

```text
source_items: 2
job_observations: 8
source_queries: 4
search_runs: 1
```

the remote Postgres database online progressive smoke with resume input:

```bash
python -m jobhunter \
  --input /tmp/currytang_resume.txt \
  --sources remotive \
  --progressive-cache \
  --agentic-search \
  --max-queries 3 \
  --fetch-details \
  --per-query-limit 3 \
  --detail-limit 2 \
  --detail-timeout 2 \
  --set-preference result_count=5 \
  --set-preference output_format=tsv \
  --set-preference target_roles="machine learning engineer,software engineer,quantitative researcher,quant research engineer,research scientist" \
  --set-preference industries="quant,AI,startup,trading"
```

Postgres counts after the smoke:

```text
source_items: 63
source_items with detail_text: 30
job_observations: 349
source_queries: 35
search_runs: 2
normalized jobs: 63
logical duplicate groups in jobs: 0
```

Output file:

```text
/tmp/remote-postgres-currytang-remotive-smoke.tsv
```

Observed ranking issue:

- The end-to-end storage and dedupe path works.
- The top smoke result was not a strong quant/MLE/SDE target because resume-derived weak terms can still create noisy matches.
- Next ranking improvement should separate mandatory role fit from soft portfolio keywords, especially for quant searches.

Architecture:

```text
agent query
  -> check the remote Postgres database-local cache
  -> fetch only missing/stale source/query coverage
  -> save raw source items
  -> normalize and dedupe into jobs
  -> save observations/provenance
  -> rank from local + fresh pool
  -> save search run and job matches
  -> optionally project to graph DB
```

Core relational tables:

- `source_queries`: normalized source/query/filter combinations.
- `fetch_runs`: every network fetch, page, cursor, status, and error.
- `source_items`: raw platform payloads before normalization.
- `jobs`: deduplicated normalized job postings.
- `job_observations`: provenance linking raw items, fetch runs, and normalized jobs.
- `search_runs`: user-facing agent runs.
- `job_matches`: ranked output per search run.

Key decision:

- Postgres is the source of truth.
- Graph DB is only a projection for relationship queries.
- Use the same `job_key` across Postgres and graph nodes.

the remote Postgres database connection model:

```bash
ssh -N -L 5433:127.0.0.1:5433 -J user@jumphost.example.edu user@db.example.edu
export JOBHUNTER_DATABASE_URL="postgresql://jobhunter:password@127.0.0.1:5433/jobhunter"
```

Remaining implementation work:

- Current code saves final ranked jobs only.
- Need a `ProgressiveJobCache` layer that stores raw source fetches and decides whether to reuse cache or fetch fresh data.

## 10. Progressive Cache MVP Implementation

Implemented:

- Added `jobhunter/cache.py`.
- Added `ProgressiveJobCache`.
- Added CLI flag:

```bash
--progressive-cache
```

New storage tables:

- `source_queries`
- `fetch_runs`
- `source_items`
- `job_observations`

New storage behavior:

- `save_source_fetch(...)`
  - records source query metadata,
  - records fetch run status,
  - upserts raw source items,
  - upserts normalized jobs,
  - inserts job observations/provenance.
- `has_fresh_source_query(...)`
  - skips source/query combinations already fetched inside the freshness TTL.
- `list_cached_jobs(...)`
  - loads locally cached normalized jobs for ranking.
- Failed source fetches are recorded but not marked fresh, so they can be retried.

CLI behavior:

```bash
python -m jobhunter \
  --input "Machine Learning Engineer with Python LLM. Remote US." \
  --offline \
  --progressive-cache \
  --store-db /tmp/jobhunter-cache.sqlite \
  --limit 2
```

With the remote Postgres database:

```bash
ssh -N -L 5433:127.0.0.1:5433 -J user@jumphost.example.edu user@db.example.edu
export JOBHUNTER_DATABASE_URL="postgresql://jobhunter:password@127.0.0.1:5433/jobhunter"

python -m jobhunter \
  --input /path/to/resume.md \
  --sources yc,a16z,linkedin,remotive,hackernews \
  --progressive-cache \
  --set-preference result_count=150 \
  --set-preference output_format=tsv
```

Validation:

```text
30 import-based tests passed.
py_compile passed.
Progressive cache smoke test:
  TSV lines: 3
  source_items: 2
  job_observations: 8
  source_queries: 4
  search_runs: 1
```

Remaining production work:

- Add broad sourcing query-track planner for 150+ result runs.
- Add source-specific TTL policies instead of one global 24-hour default.
- Add retrieval index over cached jobs, such as Postgres FTS + pgvector.
- Add graph projection worker.
