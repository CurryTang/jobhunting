# Job-Hunting Skill Live Test & Quality Evaluation — 2026-06-09

## Test Setup

- Candidate input: `https://github.com/CurryTang` (GitHub profile API + the
  `CurryTang/CurryTang` profile README + 30 most recently pushed repos).
- Inferred profile: Zhikai Chen, research scientist / ML engineer / research
  engineer / software engineer; skills led by agentic memory, LLM, graphs,
  relational foundation models; location Michigan / United States.
- Sources: remotive, hackernews (Who's Hiring), a16z, yc, linkedin (JobSpy).
- Two scenarios per round:
  - **Inferred-only**: no recorded preferences (autonomous skill behavior).
  - **With preferences**: target roles = ML engineer / research scientist /
    research engineer, Remote US, AI & developer-tools industries (the
    skill's intended post-intake behavior).
- Every run recorded a JSONL trajectory (`--trajectory-log`) and was scored by
  `scripts/evaluate_run.py` on the four requested metrics.

## Artifacts

| File | What |
| --- | --- |
| `trajectory-2026-06-09-allsources.jsonl` | baseline inferred run trajectory |
| `trajectory-2026-06-09-with-preferences.jsonl` | baseline preference run trajectory |
| `trajectory-2026-06-09-inferred-v2.jsonl` / `run-...-inferred-v2.json` | post-fix inferred run |
| `trajectory-2026-06-09-with-preferences-v2.jsonl` / `run-...-with-preferences-v2.json` | post-fix preference run |
| `eval-2026-06-09-*.md` | per-run metric reports |
| `trajectory-2026-06-09-allsources-run1-crashed.jsonl` | first attempt that exposed the `--json` crash |

## Metric Results (baseline → after fixes)

### 1. Diverse platforms

- Inferred: 5 sources, max share 36% → 4 sources, max share 32% (PASS both;
  Remotive's lone result in the baseline was the mis-matched "Head of Sales").
- With preferences: **2 sources / 8 results → 4 sources / 25 results, max
  share 60%** (FAIL → PASS). The strict role-family gate had been discarding
  every Remotive/a16z/LinkedIn candidate.

### 2. Reviewed and not stale

- All dated postings ≤ 8.3 days old in every run (HN thread is the current
  month's Who's Hiring; LinkedIn capped at 168h; a16z dated same-day).
- Live URL checks: 25/25 URLs alive in each final run (bot-blocking
  403/429/999 statuses counted as alive).
- Caveat: YC's embedded payload carries no posting dates (4–8 undated
  results per run); scoring now penalizes anything dated >30/60 days.

### 3. Match user's profile

- Inferred: 20% ML/research share with 2 non-technical mismatches
  ("Machine Learning Engineer - AI Trainer" spam, "Head of Sales") →
  24–28% share with **zero mismatches**. Software-engineering titles still
  dominate because the inferred profile legitimately contains "software
  engineer"; the skill's intake questions exist to narrow this, which the
  preference scenario confirms.
- With preferences: 88% ML share but only 8 results → **44% ML share, zero
  non-technical titles, full 25 results** (PASS). Top of list is a mix of
  AI/ML and strong-skill-overlap engineering roles with explainable
  matched-term rationales.

### 4. No duplication

- Zero exact dedupe-key collisions and zero fuzzy company+title duplicates
  in every run (PASS). Canonical-URL normalization now sorts query params
  and strips more tracking params, so cross-source URL dedupe is stricter.

## Bugs Found by the Live Test (all fixed, with regression tests)

1. `--json` crashed on `datetime.date` objects inside JobSpy raw payloads.
2. HN comments lost their line structure (`_strip_html` collapsed newlines),
   which broke company/title inference; job-seeker comments ("I'm AI
   Engineer…") were normalized into fake postings.
3. The low-signal title filter (AI Trainer / sales / annotation) only
   activated when explicit target roles were recorded, letting spam into
   inferred runs.
4. With target roles set, the role-family gate was a hard reject —
   diversity collapsed to 2 sources. Now adjacent technical matches
   (≥2 matched profile skills) survive and a per-source floor (2 slots,
   quality-thresholded) keeps every contributing source represented.
5. YC and a16z refetched their whole board for every query and returned the
   same head slice; they now fetch once per run and filter locally per query.
6. Stale-cache identity ignored location/remote (a cached Remote-US fetch
   could satisfy an onsite NYC run); the cache key now includes the full
   query identity.
7. Excluded terms matched substrings ("go" rejected "django"); JobSpy NaN
   values could render as "nan"; postings older than 30/60 days were not
   penalized; `remote=False` preferences did not penalize remote-only roles.

Test suite: 47 → 57 tests, all passing.

## Round 2 (same day): new sources + closed-posting verification

Added three free direct sources — `remoteok` (public API), `greenhouse` and
`lever` (per-company ATS board APIs; defaults cover Anthropic, DeepMind, xAI,
Scale AI, Databricks, Together AI, Mistral, Palantir, Voleon and others, all
overridable via `JOBHUNTER_GREENHOUSE_BOARDS` / `JOBHUNTER_LEVER_COMPANIES`).
Board-style sources now share a relevance ranker (`filter_and_rank`) that
requires a title hit or ≥2 body term hits and sorts before truncating, which
eliminated alphabetical board-head noise ("Account Executive" first).
The evaluator now GETs every result URL and scans for closed markers
("no longer accepting applications" etc.); postings older than 30 days only
pass freshness when the page is verified open (no redirect drift, body still
mentions the title/company).

Codex re-reviewed both batches: round-2 verdict "No P0s found"; its four P1s
(remote-region leakage like "Remote - Paris" passing a Remote-US search,
Lever `lists` content missing from descriptions, Greenhouse `updated_at`
mis-used as posting date, over-eager confirmed-open) were all fixed with
regression tests. Suite: 57 → 61 tests passing.

Final 8-source run (`run-2026-06-09-round2-final.json`, 30 results):
diversity PASS (5 sources, HN 50%, greenhouse/remoteok now contributing
Anthropic/Scale AI/Figma/Docker-class postings), freshness PASS (0 dead,
0 closed, 1 aging-but-verified-open), duplication PASS (0/0). ML-share 37%
(target 40%): just under the bar with LinkedIn rate-limited; the equivalent
run with LinkedIn available scored 40-44%. Zero non-technical mismatches in
every round-2 run.

## Round 3 (same day): direct company pages + application-ready output

Added the `companies` source: pre-default company pages (amazon, google,
meta) searched directly on each employer's own site — Amazon's JSON search
API and Google's careers payload (Meta/Microsoft have no public endpoint and
warn+skip). Configurable via `JOBHUNTER_COMPANIES` or
`.jobhunter/companies.json`, including `greenhouse:<slug>` / `lever:<slug>`
entries. Per-company results are merged round-robin so Amazon's
keyword-stuffed titles cannot crowd Google out.

Output now carries two application-ready fields per row (TSV and JSON):
`apply_url` (direct application link resolved from raw payloads, e.g.
Amazon `url_next_step`) and `outreach_message` (a profile-tailored greeting
naming the candidate, their matched skills, the specific role, and their
portfolio link).

Final 7-source run (`run-2026-06-09-round3.json`, 30 results): **all four
metrics PASS at the strongest levels of the day** — 7 sources contributing
(max share 33%), 70% ML/research share with DeepMind/Google/Amazon research
and ML roles filling the top ranks, zero closed/dead URLs, zero duplicates.
Suite: 67 tests passing.

## Known Limitations

- Remotive's full-text search has poor precision for ML queries (returns
  data-analyst/copywriter/sales posts); the ranking filters reject them, so
  Remotive may legitimately contribute zero results for this profile.
- YC postings have no dates; freshness is unknown rather than verified.
- HN company/title inference is heuristic; a few results surface as
  "Who is Hiring opportunity" with the company parsed from the first line.
- LinkedIn (JobSpy) can rate-limit; reruns may return fewer results. This
  was observed directly: a final confirmation run (`run-2026-06-09-final.json`)
  got zero LinkedIn rows (silent empty responses after several back-to-back
  test runs), leaving 3 contributing sources with HN at 62% share — just over
  the 60% diversity bar. All other metrics passed (42% ML share, zero
  mismatches, zero duplicates, all dated postings <9 days). Spacing out runs
  restores LinkedIn; this is a source quota issue, not a ranking regression.
