# Job Hunting Skill for Coding Agents

An agent skill that turns Claude Code (or Codex) into a personal job-hunting assistant. Hand it your resume, GitHub profile, or homepage and it will:

1. Build a structured candidate profile and show you what it inferred (roles, skills, portfolio highlights).
2. Ask a few focused questions — target roles, locations, remote preference, industries — instead of generic homework.
3. Search many platforms in one pass: remote boards, Hacker News "Who is Hiring", startup boards (YC, a16z), direct company career pages (Amazon, Google, any Greenhouse/Lever company), and optionally LinkedIn.
4. Rank matches with explainable reasons, deduplicate across platforms, and filter stale or spammy postings.
5. Hand you an application-ready table: every row has the **direct apply link** and a **personalized outreach message** you can send as-is.
6. Self-check the results with a built-in quality evaluator (platform diversity, freshness, profile match, duplication) before presenting them.

## Install as a Claude Code Plugin

This repo is a Claude Code plugin marketplace. Install it in two commands inside Claude Code:

```text
/plugin marketplace add CurryTang/jobhunting
/plugin install job-hunting@CurryTang
```

Then just ask, in any of these forms:

```text
/job-hunting https://github.com/yourname
$job-hunting /path/to/resume.pdf
Help me find machine learning jobs — my profile is https://github.com/yourname
```

The skill analyzes your material first, presents the inferred profile, asks a few intake questions (full-time vs internship, target roles, locations…), and only then searches. If you want it fully autonomous, say so ("search immediately with your best guesses") and it will state its assumptions instead of asking.

## Python Is Configured Automatically

**You do not set up Python, a virtualenv, or pip.** The skill ships a launcher (`scripts/jobhunter`) that finds a Python 3.10+ runtime on your machine and runs the engine directly. The core engine is pure Python standard library — zero dependencies — so it works with nothing installed.

- If any `python3.10`+ is on your PATH, that's all it needs.
- The one optional dependency — `python-jobspy`, used only by the LinkedIn source — is provisioned on demand through [`uv`](https://docs.astral.sh/uv/) in an isolated, cached environment. If `uv` isn't installed, every source except LinkedIn still works.
- If you have no Python at all but do have `uv`, the launcher lets `uv` download a suitable Python on the fly.

That's the whole setup story. The tables below are only for tuning, not required.

## Use It in Codex

Codex does not auto-discover skill files, so point it at the workflow. Either add one line to your `AGENTS.md`:

```text
When the user asks for job-hunting help, follow skills/job-hunting/SKILL.md in this repo, and run the engine via scripts/jobhunter.
```

or invoke it directly in a prompt:

```text
Read skills/job-hunting/SKILL.md and run that workflow for https://github.com/yourname
```

## Optional Tuning

- **Environment variables** (all optional — everything works with none set):

| Variable | Purpose |
| --- | --- |
| `JOBHUNTER_COMPANIES` | Narrows the direct company-page source. By default it sweeps **100+ verified company boards** (OpenAI, Anthropic, xAI, SpaceX, Databricks, Snowflake, Netflix, Uber, Stripe, Pinterest, Thinking Machines Lab, and many more). Set it to a comma list of friendly names to focus, e.g. `openai,anthropic,databricks,xai`, or add a not-yet-listed board with `greenhouse:<slug>` / `lever:<slug>` / `ashby:<slug>`. |
| `JOBHUNTER_COMPANIES_FILE` | Same as above as a JSON list file (default location `.jobhunter/companies.json`). |
| `JOBHUNTER_GREENHOUSE_BOARDS` | Boards for the Greenhouse source. Defaults to a curated AI-lab list (Anthropic, DeepMind, xAI, Scale AI, Databricks, Together AI, Stripe, Figma). |
| `JOBHUNTER_LEVER_COMPANIES` | Companies for the Lever source. Defaults to Mistral, Palantir, Plaid, Voleon. |
| `JOBHUNTER_A16Z_MARKETS` | Scope the a16z source to portfolio markets: `AI`, `Enterprise`, `Consumer`, `Crypto/Web3`, `Fintech`, `Bio Health`, `Games`, `American Dynamism`. Also `--a16z-market`; list companies with `--list-a16z-companies`. |
| `JOBHUNTER_LINKEDIN_PROXIES` | Comma list of proxies (`host:port` or `user:pass@host:port`) for the LinkedIn source — the reliable fix for its IP rate-limiting. |
| `JOBHUNTER_DATABASE_URL` | **Optional storage, disabled by default.** Set to `sqlite://$HOME/.jobhunter/jobs.sqlite` or a `postgresql://...` URL to persist deduplicated jobs and search runs across sessions. Unset it to turn storage back off. Postgres needs the `.[postgres]` extra. |

## What the Agent Searches

| Source | Access | Notes |
| --- | --- | --- |
| `companies` | Employers' own career sites | Deep sweep across **100+ verified company boards** by default (Amazon, Google, Uber custom APIs + Greenhouse/Lever/Ashby for OpenAI, Anthropic, Snowflake, Netflix, Databricks, xAI, SpaceX, Stripe, Pinterest, Thinking Machines Lab, …). Each board fetched once per run, results merge round-robin. Companies without a public API (Meta, TikTok/ByteDance, Salesforce, PayPal) warn and skip. |
| `greenhouse` / `lever` | Public ATS board APIs | Postings straight from each company's board; stale slugs are skipped silently. Tune with `JOBHUNTER_GREENHOUSE_BOARDS` / `JOBHUNTER_LEVER_COMPANIES`. |
| `remotive` / `remoteok` | Free public APIs | Remote-job boards with dates, tags, salary ranges. |
| `hackernews` | HN Algolia API | Current month's "Who is Hiring" thread; job-seeker comments are filtered out. |
| `yc` / `a16z` | Public board payloads | YC startup jobs and a16z portfolio jobs. |
| `linkedin` / `indeed` / `glassdoor` | Optional JobSpy scrapers | Need the `.[jobspy]` extra. LinkedIn pools terms + retries to soften its hard IP rate-limit (set `JOBHUNTER_LINKEDIN_PROXIES` for reliability); **Indeed and Glassdoor are broad aggregators that are far less throttled — good stand-ins when LinkedIn returns nothing**. |

## What You Get Back

Results default to TSV (paste straight into a spreadsheet). Each row carries:

- rank, score, title, company, source, location, salary
- `url` — the job listing
- `apply_url` — the direct application link (e.g. Amazon's apply endpoint, Lever's apply page)
- `matched_terms` and a one-line rationale explaining *why* it matched you
- `outreach_message` — a short, sendable greeting generated from your profile: who you are, which of your matched skills fit this role, and your portfolio link
- `contact_emails` and `linkedin_contacts` — who to reach: emails pulled from the posting (HN posts often include them) plus role-based guesses (`careers@`, `recruiting@`) from the company domain, and ready-made LinkedIn people-search links for the recruiter, the team's hiring manager, and the head of the relevant function

Prefer a browsable page over a table? Ask for **HTML output** (`--html`) and you get a self-contained `jobs.html` — one card per job with an Apply button, matched-skill chips, a live filter box, and a one-click "Copy" button on each outreach message. It opens straight from disk with no internet needed.

Every live search also writes a JSONL **trajectory log** (profile → planned queries → per-source fetch/keep counts → errors → final ranking), and the skill runs a **quality evaluator** that scores the run on four metrics — platform diversity, freshness (posting age plus live "is this still open?" URL checks), profile match, and duplication — and iterates if any metric needs attention.

## Privacy & Footprint

- No accounts, API keys, or paid services required; every source is a public endpoint.
- Nothing is stored unless you opt in via `JOBHUNTER_DATABASE_URL`.
- Your resume text never leaves your machine except as search keywords sent to the job boards.

## Community

<img src="artifact/wechat-group-qrcode.jpg" alt="WeChat group QR code" width="320">

## Repository Layout

- `.claude-plugin/` — plugin and marketplace manifests for Claude Code.
- `skills/job-hunting/SKILL.md` — the agent-facing skill: intake, preference questions, source selection, search, quality verification, presentation, and follow-ups.
- `scripts/jobhunter` / `scripts/evaluate` — zero-config launchers that resolve a Python 3.10+ runtime automatically; the skill invokes these.
- `jobhunter/` — the search engine the skill drives (profile builder, query planner, ranking agent, platform adapters, optional storage/cache/graph).
- `scripts/evaluate_run.py` — the run-quality evaluator (invoked through `scripts/evaluate`).
- `examples/` — sample resume input for offline demos.
- `docs/` — architecture and storage design notes.
- `tests/` — test suite. Contributors: `python -m pytest` (or `uv run pytest`).
