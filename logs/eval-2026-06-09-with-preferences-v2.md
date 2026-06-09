# Run quality evaluation: run-2026-06-09-with-preferences-v2.json

- Generated: 2026-06-09T22:10:29.720996+00:00
- Results: 25
- Profile roles: research scientist, machine learning engineer, software engineer, research engineer
- Target roles: machine learning engineer, research scientist, research engineer

## 1. Platform diversity

- hackernews: 15
- a16z: 5
- yc: 4
- jobspy:linkedin: 1

- Distinct sources in results: 4
- Largest single-source share: 60%
- Verdict: PASS (target: >=3 sources, no source >60%)

## 2. Freshness (not stale)

- Dated postings: 21/25 (median age 7.9 days, max 8.3 days)
- Postings without a date: 4/25

Live URL checks:
- URLs checked: 25, dead or erroring: 0 (403/405/429/999 bot blocks counted as alive)
- Verdict: PASS (target: nothing >30 days old, at most half undated)

## 3. Profile match

- ml/research: 11
- software: 10
- unclassified: 4

- ML/research share for an ML/research profile: 44%
- Verdict: PASS (target: zero non-technical mismatches; >=40% ML/research for this profile)

## 4. Duplication

- Exact dedupe-key collisions: 0
- Verdict: PASS (target: zero exact and fuzzy duplicates)
