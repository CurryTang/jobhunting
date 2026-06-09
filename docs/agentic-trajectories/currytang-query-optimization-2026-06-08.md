# CurryTang Query and Ranking Optimization

Date: 2026-06-08

Input resume:

```text
/tmp/currytang_resume.txt
source PDF: /path/to/resume.pdf
```

## Goal

Run several query/ranking experiments for quantitative researcher, ML researcher/MLE, SDE/backend/platform roles, then fix the parts that produced noisy or sparse results.

## Round 1: Query Plan Audit

Tracks tested:

- Quant: `quantitative researcher`, `quant research engineer`; industries `quant,trading,finance`.
- MLE/research: `machine learning engineer`, `research scientist`, `research engineer`; industries `AI labs,startup`.
- SDE/infra: `software engineer`, `backend engineer`, `platform engineer`; industries `AI,startup,developer tools`.
- Broad: MLE + SDE + quant + research roles.

Findings:

- Explicit target-role searches still generated generic keyword-only queries such as resume keyword fragments.
- MLE query strings were too long, for example `machine learning engineer machine learning python llm post-training`, which hurt source recall.
- `AI` industry matching used substring logic, so words/company names containing `ai` could be counted as AI evidence.
- Quant evidence treated soft words such as `market`, `portfolio`, `finance`, and `options` as strong quant evidence.
- Long Hacker News posts over-scored because the same role term could be counted as target role, profile role, and query role.

## Round 2: Query and Role Gate Fixes

Implemented:

- Disabled generic keyword-only queries when `target_roles` are explicit.
- Added compact role query composition:
  - `machine learning engineer python llm`
  - `research scientist machine learning python`
  - `research engineer machine learning python`
  - `software engineer python backend`
- Added whole-word matching for industries and company stages.
- Split quant evidence into strong and soft terms.
- Added role-family gate so non-technical titles do not pass only because they mention AI/LLM/finance.

Observed results:

- Quant free-source run became strict and returned Nof1, a strong AI-trading research-engineering match.
- SDE free-source run returned relevant YC/HN/backend/platform roles.
- MLE free-source run was sparse because YC/a16z/Remotive/HN had limited current MLE hits under small query budgets.

## Round 3: LinkedIn Recall Check

LinkedIn/JobSpy was tested with Python 3.11.

MLE/research command shape:

```bash
/opt/homebrew/bin/python3.11 -m jobhunter \
  --input /tmp/currytang_resume.txt \
  --sources linkedin \
  --max-queries 4 \
  --per-query-limit 10 \
  --set-preference result_count=12 \
  --set-preference output_format=tsv \
  --set-preference target_roles="machine learning engineer,research scientist,research engineer" \
  --set-preference preferred_locations="New York,Remote US" \
  --set-preference remote=true \
  --set-preference industries="AI labs,startup"
```

Quant command shape:

```bash
/opt/homebrew/bin/python3.11 -m jobhunter \
  --input /tmp/currytang_resume.txt \
  --sources linkedin \
  --max-queries 4 \
  --per-query-limit 10 \
  --set-preference result_count=12 \
  --set-preference output_format=tsv \
  --set-preference target_roles="quantitative researcher,quant research engineer" \
  --set-preference preferred_locations="New York,Remote US" \
  --set-preference remote=true \
  --set-preference industries="quant,trading,finance"
```

Good quant examples:

- Jump Trading - Quantitative Researcher | Trading Team
- Jump Trading - AI Research Scientist | Research & Development
- Trexquant Investment LP - Quantitative Researcher

Initial MLE issue:

- `Machine Learning Engineer - AI Trainer` from DataAnnotation appeared because the title had `Machine Learning Engineer`, but the actual job category was low-signal for this search.

Implemented:

- Added low-signal technical-title filtering for trainer/annotation/editor/marketing/sales/recruiter/product/designer/operations titles.

Improved MLE examples:

- Datadog - AI Research Scientist, DAIR
- Meta - AI Research Scientist, SysML - FAIR
- Millennium - ML Research Scientist, Deep Learning & Transformer Architectures
- Morgan Stanley - Machine Learning Researcher
- Google - Senior Research Engineer
- Meta - Research Engineer, MRS AI

## Round 4: Role Alias and Score Inflation Fixes

Implemented:

- Added role aliases:
  - `machine learning engineer` -> `ml engineer`, `machine learning researcher`, `ml researcher`, `applied scientist`, `ai engineer`
  - `research scientist` -> `machine learning researcher`, `ml researcher`, `ai research scientist`, `applied scientist`
  - `quantitative researcher` -> `quant researcher`, `quantitative research scientist`, `alpha researcher`
  - `quant research engineer` -> `quantitative research engineer`, `quant developer`, `quantitative developer`
- Changed scoring so the same normalized term only contributes its highest weight once.
- Disabled generic resume keyword scoring when target roles are explicit.
- Stopped scoring candidate seniority `intern` unless the user explicitly searches for internships.

Broad run command:

```bash
/opt/homebrew/bin/python3.11 -m jobhunter \
  --input /tmp/currytang_resume.txt \
  --sources linkedin,remotive,hackernews,a16z,yc \
  --agentic-search \
  --max-queries 12 \
  --per-query-limit 8 \
  --set-preference result_count=30 \
  --set-preference output_format=tsv \
  --set-preference target_roles="machine learning engineer,software engineer,backend engineer,platform engineer,quantitative researcher,quant research engineer,research scientist,research engineer" \
  --set-preference preferred_locations="New York,Remote US" \
  --set-preference remote=true \
  --set-preference industries="quant,trading,AI labs,startup,developer tools"
```

Latest broad output:

```text
/tmp/jobhunter-exp-broad-v6.tsv
```

Coverage in latest broad top 30:

```text
jobspy:linkedin: 15
hackernews: 11
a16z: 2
yc: 2

quant-like: 4
MLE/research-like: 18
SDE-like: 17
low-signal title hits: 0
```

Representative top results:

- Nof1 - Research Engineer / Full-Stack Engineer / Infrastructure Engineer, AI trading research lab.
- Jump Trading - AI Research Scientist | Research & Development.
- Jump Trading - Research Engineer, Pre-Training.
- Jump Trading - Quantitative Researcher | Trading Team.
- Waymo - Staff Machine Learning Engineer, Multi-Modal Perception.
- Datadog - AI Research Scientist, DAIR.
- Meta - AI Research Scientist, SysML - FAIR.
- Anthropic - Research Engineer, Machine Learning (RL Velocity).
- Anthropic - Research Engineer, Universes.
- Google - Senior Research Engineer.

## Remaining Improvements

- Hacker News posts are still noisy because one post can describe multiple roles in a single long comment. Better extraction should split HN comments into role-level postings before ranking.
- Quant coverage is good from LinkedIn/JobSpy but should be augmented with official quant career pages for Jane Street, Two Sigma, Citadel, HRT, DRW, Optiver, Point72, IMC, Jump, and G-Research.
- Broad mixed search should eventually enforce per-track quotas, for example 50 MLE/research, 50 SDE/infra, 50 quant, instead of one global ranking list.
- A reranker should use title/company/source reliability features separately from keyword evidence, especially for HN comments.

## Verification

```text
py_compile passed for jobhunter modules.
41 import-based tests passed.
```
