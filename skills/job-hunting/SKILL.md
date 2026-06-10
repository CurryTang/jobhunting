---
name: job-hunting
description: Use this skill when a user wants help searching for jobs from a resume, homepage, GitHub profile, or other candidate material.
---

# Job Hunting

Use this skill when a user wants help searching for jobs from a resume, homepage, GitHub profile, or other candidate material.

## Workflow

1. Intake candidate material.
   - Accept a local resume file, raw resume text, homepage URL, or GitHub profile URL.
   - Do not expect the user to provide target roles, highlighted projects, locations, or search preferences upfront.
   - If the user provides only candidate material, infer the candidate's strongest options and ask the next questions yourself.
   - Use `jobhunter.profile.load_input` to normalize the input into text.
   - Use `jobhunter.profile.build_user_profile` to build a structured `UserProfile`.

2. Inspect and refine the profile.
   - Check roles, skills, locations, seniority, links, and keywords.
   - Use `profile.evidence["portfolio_highlights"]` to inspect the strongest resume/homepage/GitHub points.
   - Use `adaptive_preference_questions(profile)` to identify missing user preferences.
   - Ask focused intake questions before search, in this order when relevant:
     - **Full-time, internship, or both.** Ask this early — it is one of the first questions. Never infer it silently: a resume saying "PhD student" or "research intern" does NOT mean the candidate wants an internship. Record the answer in `job_types`.
     - Which portfolio highlights should be emphasized most.
     - Which role tracks should be prioritized from the inferred options.
     - Preferred locations and remote/hybrid/onsite preference.
     - Preferred industries, company stages, salary floor, and visa needs.
     - How many jobs to return.
     - Output format. Default to TSV when the user does not choose a format.
   - Present the questions as concrete choices derived from the profile, not as generic open-ended homework for the user.
   - Record answers with `update_preferences` and `save_preferences`, then rebuild or reuse the profile with those preferences.
   - If the profile is clearly missing core facts, ask one concise clarification before running a broad search.
   - If the user only asked for intake, stop after the questions and wait for answers.
   - If the user wants autonomous progress or explicitly asks to search immediately, proceed with inferred preferences and state the assumptions. **Default to full-time when the user has not answered** — internship postings are ranked lower (set `job_types="full-time"` to make this explicit), unless the candidate clearly signals they want internships.

3. Select sources.
   - Prefer free structured sources first: `RemotivePlatform` and `RemoteOKPlatform` for remote roles, `HackerNewsWhoIsHiringPlatform` for HN Who's Hiring.
   - Use `GreenhousePlatform` and `LeverPlatform` for direct employer boards (AI labs and strong engineering brands by default; tune the company lists with `JOBHUNTER_GREENHOUSE_BOARDS` / `JOBHUNTER_LEVER_COMPANIES` to fit the candidate's targets).
   - Use `CompanyBoardsPlatform` (`--sources companies`) when the user wants specific employers searched directly. Pre-defaults are amazon/google/meta; configure with `JOBHUNTER_COMPANIES` or `.jobhunter/companies.json`, including `greenhouse:<slug>` / `lever:<slug>` entries. Ask the user which target companies to add when they name employers.
   - Use `LinkedInJobSpyPlatform` when the user wants LinkedIn and `python-jobspy` is installed under Python 3.10+. LinkedIn silently returns zero rows when rate-limited; do not treat an empty LinkedIn result as "no jobs".
   - Use `A16ZPlatform` for a16z portfolio jobs and `YCJobsPlatform` for YC startup jobs.
   - Check `PLATFORM_REGISTRY` for implemented and planned sources.
   - Treat Glassdoor and Handshake as planned/restricted until a compliant adapter exists.
   - Use `OfflineDemoPlatform` only for tests, demos, or no-network situations.
   - Add paid, authenticated, or restricted platforms only behind the `JobPlatform` interface and only through compliant access paths.

4. Run agentic search.
   - Use `QueryPlanner` to generate role/skill/location queries from the profile.
   - Use `JobSearchAgent` to search each selected platform, normalize postings, deduplicate, rank, and produce explainable matches.
   - Always pass `--trajectory-log logs/trajectory-<date>.jsonl` for live runs so the search is auditable (queries, per-source fetch/keep counts, errors, final ranking).
   - Refine by adding/removing query terms when the result set is too broad, too sparse, or mismatched.
   - Retry loop: if fewer results than requested came back, or fewer than 3 sources contributed, rerun with broader queries (`--agentic-search`), higher `--per-query-limit`, more `--max-queries`, or relaxed target roles before reporting a sparse list.

5. Verify quality before presenting.
   - Run `"$CLAUDE_PLUGIN_ROOT/scripts/evaluate" <run.json> --check-urls --report <eval.md>` on the JSON output.
   - The evaluator scores four metrics: platform diversity, freshness (posting age + live URL checks), profile match, and duplication.
   - If a metric reports NEEDS ATTENTION, iterate (broaden sources, tighten preferences, drop stale results) rather than presenting a weak list.

6. Present results.
   - Lead with ranked jobs, company, source, location, salary if available, URL, and why it matched.
   - Every result carries `apply_url` (direct application link) and `outreach_message` (a profile-tailored greeting); surface both so the user can apply and reach out immediately, and offer to refine the message tone per company.
   - Offer an HTML view (`--html > jobs.html`) when the user wants something nicer than a table: it produces a self-contained, browsable page with apply buttons, matched-term chips, a filter box, and one-click-copy outreach messages. Save it to a file and tell the user the path (or open it).
   - Always report: which sources contributed and which returned nothing or errored, freshness caveats (e.g. YC postings carry no dates), and any assumptions made on the user's behalf.
   - Call out source limitations, especially for unstructured HN comments or platforms without public APIs.
   - Offer concrete follow-ups: verify shortlisted jobs are still open before applying, export the shortlist (TSV/JSON), draft tailored resume bullets or outreach notes for top matches, add sources, or record preferences for the next run.

## Optional Storage

Persistence is disabled by default; runs are stateless. To record jobs and search runs across sessions, set `JOBHUNTER_DATABASE_URL` (SQLite or Postgres) in the environment before running — see the README's storage section. Never require storage for a basic search.

## Running the Engine

Always invoke the engine through the bundled launcher, never a bare `python`:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/jobhunter" <args>
```

`CLAUDE_PLUGIN_ROOT` is set by Claude Code to this skill's install directory. When it is unset (e.g. running from a clone), use the repo-relative path `scripts/jobhunter`. The launcher is zero-config: it finds a Python 3.10+ runtime automatically and runs the dependency-free engine with no venv and no pip. The user never sets up Python. The only optional dependency (python-jobspy, for the LinkedIn source) is provisioned on demand through `uv`; if `uv` is missing, every source except LinkedIn still works. The quality evaluator has its own matching launcher at `scripts/evaluate`.

## Useful Commands

Offline deterministic demo:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/jobhunter" --input examples/resume.md --offline --limit 5
```

Live Remotive demo:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/jobhunter" --input examples/resume.md --sources remotive --limit 5
```

Startup boards and direct company pages:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/jobhunter" --input examples/resume.md --sources a16z,yc,companies --limit 10
```

Preference questions and recorded answers:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/jobhunter" --input examples/resume.md --offline --show-questions
"$CLAUDE_PLUGIN_ROOT/scripts/jobhunter" --input examples/resume.md --preferences-file .jobhunter/preferences.json --set-preference job_types="full-time" --set-preference target_roles="research scientist,machine learning engineer" --set-preference preferred_locations="Remote US,New York" --set-preference remote=true --sources a16z,yc,companies
```

JSON output and quality evaluation:

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/jobhunter" --input examples/resume.md --sources remotive,companies --json > run.json
"$CLAUDE_PLUGIN_ROOT/scripts/evaluate" run.json --check-urls --report eval.md
```

LinkedIn (python-jobspy is auto-provisioned via uv; no manual install):

```bash
"$CLAUDE_PLUGIN_ROOT/scripts/jobhunter" --input examples/resume.md --sources linkedin --limit 10
```

## Skill Invocation Examples

Minimal GitHub portfolio intake:

```text
$job-hunting https://github.com/CurryTang
```

Minimal resume intake:

```text
$job-hunting /path/to/resume.pdf
```

Expected behavior:

- Analyze the material first.
- Show inferred roles, skills, locations, and portfolio highlights.
- Ask early whether the candidate wants full-time, internship, or both; default to full-time and rank internships lower when unanswered.
- Ask the user which inferred highlights and role tracks to prioritize.
- Ask location, remote, industry, stage, salary, and visa questions only when missing.
- Ask how many jobs to return and which output format to use; use TSV by default.
- Do not start search until the user answers, unless the user explicitly asks for autonomous search.
