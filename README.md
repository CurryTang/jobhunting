# Job Hunting Skill for Coding Agents

An agent skill that turns Claude Code (or Codex) into a personal job-hunting assistant. Hand it your resume, GitHub profile, or homepage and it will:

1. Build a structured candidate profile and show you what it inferred (roles, skills, portfolio highlights).
2. Ask a few focused questions — target roles, locations, remote preference, industries — instead of generic homework.
3. Search many platforms in one pass: remote boards, Hacker News "Who is Hiring", startup boards (YC, a16z), direct company career pages (Amazon, Google, any Greenhouse/Lever company), and optionally LinkedIn.
4. Rank matches with explainable reasons, deduplicate across platforms, and filter stale or spammy postings.
5. Hand you an application-ready table: every row has the **direct apply link** and a **personalized outreach message** you can send as-is.
6. Self-check the results with a built-in quality evaluator (platform diversity, freshness, profile match, duplication) before presenting them.

## Use It in Claude Code

Install once:

```bash
git clone <this-repo> jobhunting && cd jobhunting
python3.11 -m venv .venv && .venv/bin/pip install -e ".[jobspy]"

# Make the skill available to Claude Code (user-level):
mkdir -p ~/.claude/skills
ln -s "$(pwd)/skills/job-hunting" ~/.claude/skills/job-hunting
```

Then just ask, in any of these forms:

```text
/job-hunting https://github.com/yourname
$job-hunting /path/to/resume.pdf
Help me find machine learning jobs — my profile is https://github.com/yourname
```

The skill instructs the agent to analyze your material first, present the inferred profile, ask its intake questions, and only then search. If you want it fully autonomous, say so ("search immediately with your best guesses") and it will state its assumptions instead of asking.

## Use It in Codex

Codex does not auto-discover skill files, so point it at the workflow. Either add one line to your `AGENTS.md`:

```text
When the user asks for job-hunting help, follow skills/job-hunting/SKILL.md in this repo.
```

or invoke it directly in a prompt:

```text
Read skills/job-hunting/SKILL.md and run that workflow for https://github.com/yourname
```

## Environment Preparation

The skill drives a small bundled engine; the agent runs it for you. You only prepare the environment:

- **Python 3.10+** (3.11 recommended). `pip install -e .` from the repo root — the core has zero dependencies.
- **Optional extras**: `.[jobspy]` enables the LinkedIn source (Python 3.10+ only; LinkedIn rate-limits aggressively), `.[postgres]` enables Postgres storage, `.[graph]` enables the Kuzu graph boost.
- **Environment variables** (all optional — everything works with none set):

| Variable | Purpose |
| --- | --- |
| `JOBHUNTER_COMPANIES` | Companies for the direct company-page source. Default `amazon,google,meta`. Accepts `greenhouse:<slug>` / `lever:<slug>` entries for any company on those ATSes, e.g. `amazon,google,greenhouse:anthropic,lever:mistral`. |
| `JOBHUNTER_COMPANIES_FILE` | Same as above as a JSON list file (default location `.jobhunter/companies.json`). |
| `JOBHUNTER_GREENHOUSE_BOARDS` | Boards for the Greenhouse source. Defaults to a curated AI-lab list (Anthropic, DeepMind, xAI, Scale AI, Databricks, Together AI, Stripe, Figma). |
| `JOBHUNTER_LEVER_COMPANIES` | Companies for the Lever source. Defaults to Mistral, Palantir, Plaid, Voleon. |
| `JOBHUNTER_DATABASE_URL` | **Optional storage, disabled by default.** Set to `sqlite://$HOME/.jobhunter/jobs.sqlite` or a `postgresql://...` URL to persist deduplicated jobs and search runs across sessions. Unset it to turn storage back off. Postgres needs the `.[postgres]` extra. |

## What the Agent Searches

| Source | Access | Notes |
| --- | --- | --- |
| `companies` | Employers' own career sites | Pre-defaults amazon/google/meta; Amazon and Google answer with live postings and direct apply links; unsupported sites (meta, microsoft) are skipped with a warning. Results merge round-robin so no company crowds out the rest. |
| `greenhouse` / `lever` | Public ATS board APIs | Postings straight from each company's board; stale slugs are skipped silently. |
| `remotive` / `remoteok` | Free public APIs | Remote-job boards with dates, tags, salary ranges. |
| `hackernews` | HN Algolia API | Current month's "Who is Hiring" thread; job-seeker comments are filtered out. |
| `yc` / `a16z` | Public board payloads | YC startup jobs and a16z portfolio jobs. |
| `linkedin` | Optional JobSpy scraper | Needs the `.[jobspy]` extra; silently returns nothing when rate-limited, so the skill never treats an empty LinkedIn result as "no jobs". |

## What You Get Back

Results default to TSV (paste straight into a spreadsheet). Each row carries:

- rank, score, title, company, source, location, salary
- `url` — the job listing
- `apply_url` — the direct application link (e.g. Amazon's apply endpoint, Lever's apply page)
- `matched_terms` and a one-line rationale explaining *why* it matched you
- `outreach_message` — a short, sendable greeting generated from your profile: who you are, which of your matched skills fit this role, and your portfolio link

Every live search also writes a JSONL **trajectory log** (profile → planned queries → per-source fetch/keep counts → errors → final ranking), and the skill runs a **quality evaluator** that scores the run on four metrics — platform diversity, freshness (posting age plus live "is this still open?" URL checks), profile match, and duplication — and iterates if any metric needs attention.

## Privacy & Footprint

- No accounts, API keys, or paid services required; every source is a public endpoint.
- Nothing is stored unless you opt in via `JOBHUNTER_DATABASE_URL`.
- Your resume text never leaves your machine except as search keywords sent to the job boards.

## Community

<img src="artifact/wechat-group-qrcode.jpg" alt="WeChat group QR code" width="320">

## Repository Layout

- `skills/job-hunting/SKILL.md` — the agent-facing skill: intake, preference questions, source selection, search, quality verification, presentation, and follow-ups.
- `jobhunter/` — the search engine the skill drives (profile builder, query planner, ranking agent, platform adapters, optional storage/cache/graph).
- `scripts/evaluate_run.py` — the run-quality evaluator.
- `examples/` — sample resume input for offline demos.
- `docs/` — architecture and storage design notes.
- `tests/` — test suite (`.venv/bin/python -m pytest`).
