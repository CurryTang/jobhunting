"""Evaluate the quality of a jobhunter search run.

Usage:
    python scripts/evaluate_run.py RUN_JSON [--check-urls] [--report PATH]

Scores a `--json` run output on four metrics:
  1. Platform diversity: how many distinct sources produced results.
  2. Freshness: posting-date age and (optionally) live URL checks.
  3. Profile match: role-family fit between each job title and the profile.
  4. Duplication: exact dedupe-key collisions and fuzzy company+title dupes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jobhunter.models import JobPosting  # noqa: E402
from jobhunter.storage import _norm_company, _norm_title, job_key  # noqa: E402

ROLE_FAMILIES = {
    "ml/research": (
        "machine learning",
        "ml engineer",
        "research",
        "scientist",
        "ai engineer",
        "ai researcher",
        "applied scientist",
        "deep learning",
        "llm",
        "nlp",
        "data scientist",
    ),
    "software": (
        "software engineer",
        "developer",
        "backend",
        "frontend",
        "full stack",
        "full-stack",
        "platform engineer",
        "infrastructure",
        "sre",
        "site reliability",
        "founding engineer",
        "devops",
        "systems engineer",
        "engineer",
    ),
}

NON_TECHNICAL_TERMS = (
    "sales",
    "marketing",
    "recruiter",
    "account executive",
    "customer success",
    "trainer",
    "annotator",
    "annotation",
    "copywriter",
    "video editor",
    "head of sales",
    "operations manager",
)


def evaluate(run_path: Path, *, check_urls: bool = False) -> str:
    data = json.loads(run_path.read_text(encoding="utf-8"))
    matches = data.get("matches", [])
    profile = data.get("profile", {})
    requested_sources = sorted({m["job"]["source"].split(":")[0] for m in matches})
    lines: list[str] = []
    lines.append(f"# Run quality evaluation: {run_path.name}")
    lines.append("")
    lines.append(f"- Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append(f"- Results: {len(matches)}")
    lines.append(f"- Profile roles: {', '.join(profile.get('roles', [])) or '-'}")
    prefs = profile.get("preferences", {})
    lines.append(f"- Target roles: {', '.join(prefs.get('target_roles', [])) or '(none recorded)'}")
    lines.append("")

    # 1. Platform diversity -------------------------------------------------
    source_counts = Counter(m["job"]["source"] for m in matches)
    lines.append("## 1. Platform diversity")
    lines.append("")
    for source, count in source_counts.most_common():
        lines.append(f"- {source}: {count}")
    top_share = (source_counts.most_common(1)[0][1] / len(matches)) if matches else 0.0
    lines.append("")
    lines.append(f"- Distinct sources in results: {len(source_counts)}")
    lines.append(f"- Largest single-source share: {top_share:.0%}")
    lines.append(f"- Verdict: {'PASS' if len(source_counts) >= 3 and top_share <= 0.6 else 'NEEDS ATTENTION'} (target: >=3 sources, no source >60%)")
    lines.append("")

    # 2. Freshness ----------------------------------------------------------
    now = datetime.now(timezone.utc)
    ages: list[float] = []
    undated = 0
    aged: list[tuple[str, str, str, int]] = []
    for m in matches:
        posted = m["job"].get("posted_at")
        if not posted:
            undated += 1
            continue
        try:
            dt = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
        except ValueError:
            undated += 1
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_days = (now - dt).total_seconds() / 86400
        ages.append(age_days)
        if age_days > 30:
            aged.append((m["job"]["title"], m["job"]["company"], m["job"]["url"], round(age_days)))
    lines.append("## 2. Freshness (not stale)")
    lines.append("")
    if ages:
        lines.append(f"- Dated postings: {len(ages)}/{len(matches)} (median age {sorted(ages)[len(ages)//2]:.1f} days, max {max(ages):.1f} days)")
    lines.append(f"- Postings without a date: {undated}/{len(matches)}")

    closed = 0
    confirmed_open: set[str] = set()
    if check_urls:
        lines.append("")
        lines.append("Live URL checks (status + closed-posting markers):")
        dead = 0
        for m in matches:
            url = m["job"]["url"]
            status, marker, verified = _check_url(url, expect_terms=(m["job"]["title"], m["job"]["company"]))
            ok = isinstance(status, int) and status < 400
            blocked = isinstance(status, int) and status in (403, 405, 429, 999)
            if ok and marker:
                closed += 1
                lines.append(f"- CLOSED ('{marker}'): {m['job']['title']} - {m['job']['company']} {url}")
            elif not ok and not blocked:
                dead += 1
                lines.append(f"- DEAD/ERROR [{status}] {url}")
            elif ok and verified:
                confirmed_open.add(url)
        lines.append(
            f"- URLs checked: {len(matches)}, dead or erroring: {dead}, marked closed on page: {closed} "
            "(403/405/429/999 bot blocks counted as alive)"
        )

    # An old posting whose page is confirmed open (no closed marker) is
    # "aging", not stale: greenhouse/lever dates are update timestamps and
    # long-running roles stay genuinely open.
    stale = []
    for title, company, url, age in aged:
        if url in confirmed_open:
            lines.append(f"- AGING but confirmed still open ({age} days): {title} - {company}")
        else:
            stale.append((title, company, age))
    for title, company, age in stale:
        lines.append(f"- STALE (> 30 days, not verified open): {title} - {company} ({age} days)")
    fresh_ok = not stale and undated <= len(matches) // 2 and closed == 0
    lines.append(
        f"- Verdict: {'PASS' if fresh_ok else 'NEEDS ATTENTION'} "
        "(target: zero closed postings, nothing >30 days unless verified open, at most half undated)"
    )
    lines.append("")

    # 3. Profile match ------------------------------------------------------
    target_roles = [r.lower() for r in prefs.get("target_roles", [])]
    profile_roles = [r.lower() for r in profile.get("roles", [])]
    wants_ml = any("machine learning" in r or "research" in r or "scientist" in r for r in (target_roles or profile_roles))
    lines.append("## 3. Profile match")
    lines.append("")
    family_counts: Counter[str] = Counter()
    mismatches = []
    for m in matches:
        title = m["job"]["title"].lower()
        family = _classify_title(title)
        family_counts[family] += 1
        if family == "non-technical" or (family == "unclassified" and not m.get("matched_terms")):
            mismatches.append((m["job"]["title"], m["job"]["company"], m["score"]))
    for family, count in family_counts.most_common():
        lines.append(f"- {family}: {count}")
    ml_share = family_counts["ml/research"] / len(matches) if matches else 0.0
    lines.append("")
    if wants_ml:
        lines.append(f"- ML/research share for an ML/research profile: {ml_share:.0%}")
    for title, company, score in mismatches:
        lines.append(f"- MISMATCH: {title} - {company} (score {score})")
    match_ok = not mismatches and (not wants_ml or ml_share >= 0.4)
    lines.append(f"- Verdict: {'PASS' if match_ok else 'NEEDS ATTENTION'} (target: zero non-technical mismatches; >=40% ML/research for this profile)")
    lines.append("")

    # 4. Duplication ----------------------------------------------------------
    lines.append("## 4. Duplication")
    lines.append("")
    keys = Counter()
    fuzzy = Counter()
    for m in matches:
        job = m["job"]
        posting = JobPosting(
            source=job["source"],
            source_id=job.get("source_id") or "",
            title=job["title"],
            company=job["company"],
            url=job["url"],
            location=job.get("location"),
        )
        keys[job_key(posting)] += 1
        fuzzy[(_norm_company(job["company"]), _norm_title(job["title"]))] += 1
    exact_dupes = {k: c for k, c in keys.items() if c > 1}
    fuzzy_dupes = {k: c for k, c in fuzzy.items() if c > 1}
    lines.append(f"- Exact dedupe-key collisions: {len(exact_dupes)}")
    for (company, title), count in fuzzy_dupes.items():
        lines.append(f"- FUZZY DUPLICATE x{count}: {company} / {title}")
    lines.append(f"- Verdict: {'PASS' if not exact_dupes and not fuzzy_dupes else 'NEEDS ATTENTION'} (target: zero exact and fuzzy duplicates)")
    lines.append("")
    return "\n".join(lines)


def _classify_title(title: str) -> str:
    if any(re.search(r"(?<![a-z])" + re.escape(term) + r"(?![a-z])", title) for term in NON_TECHNICAL_TERMS):
        return "non-technical"
    for family, terms in ROLE_FAMILIES.items():
        if any(term in title for term in terms):
            return family
    return "unclassified"


CLOSED_MARKERS = (
    "no longer accepting applications",
    "this job is no longer available",
    "this position is no longer available",
    "position has been filled",
    "this role has been filled",
    "job has been closed",
    "this posting has closed",
    "this job has expired",
    "job not found",
    "posting not found",
)


def _check_url(url: str, *, expect_terms: tuple[str, ...] = (), timeout: float = 6.0) -> tuple[int | str, str | None, bool]:
    """Return (status, closed_marker, verified_open).

    verified_open requires more than a 2xx: expired ATS links often redirect
    to a generic careers page with no closed text, so the final URL must not
    drift to a different path and the body must still mention the job title
    or company.
    """

    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (jobhunter-eval)"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(300_000).decode("utf-8", errors="replace").lower()
            marker = next((m for m in CLOSED_MARKERS if m in body), None)
            same_page = _same_path(url, response.geturl())
            mentions = any(term.lower() in body for term in expect_terms if term)
            return response.status, marker, bool(same_page and mentions)
    except urllib.error.HTTPError as exc:
        return exc.code, None, False
    except Exception as exc:  # noqa: BLE001
        return str(exc), None, False


def _same_path(requested: str, final: str) -> bool:
    from urllib.parse import urlparse

    return urlparse(requested).path.rstrip("/") == urlparse(final).path.rstrip("/")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_json", type=Path)
    parser.add_argument("--check-urls", action="store_true", help="HEAD-check every result URL for liveness.")
    parser.add_argument("--report", type=Path, help="Write the markdown report to this path.")
    args = parser.parse_args()
    report = evaluate(args.run_json, check_urls=args.check_urls)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(report, encoding="utf-8")
        print(f"wrote {args.report}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
