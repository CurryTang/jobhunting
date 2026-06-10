from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from typing import Any

from jobhunter.models import JobMatch, JobPosting, SearchQuery, UserProfile
from jobhunter.outreach import build_outreach_message, resolve_apply_url


def render_html_from_run(data: dict[str, Any]) -> str:
    """Render HTML from a saved `--json` run dict, no re-fetching needed."""

    profile = _profile_from_dict(data.get("profile") or {})
    matches = [_match_from_dict(item) for item in data.get("matches") or []]
    return render_html(profile, matches, source_errors=data.get("source_errors") or ())


def _profile_from_dict(d: dict[str, Any]) -> UserProfile:
    fields = {f: d.get(f) for f in ("raw_text", "name", "headline", "seniority")}
    fields["raw_text"] = fields.get("raw_text") or ""
    for seq in ("roles", "skills", "locations", "links", "keywords"):
        fields[seq] = tuple(d.get(seq) or ())
    return UserProfile(**fields)


def _match_from_dict(item: dict[str, Any]) -> JobMatch:
    j = item.get("job") or {}
    posted = j.get("posted_at")
    posted_at = None
    if posted:
        try:
            posted_at = datetime.fromisoformat(str(posted).replace("Z", "+00:00"))
        except ValueError:
            posted_at = None
    job = JobPosting(
        source=j.get("source", ""),
        source_id=j.get("source_id", ""),
        title=j.get("title", ""),
        company=j.get("company", ""),
        url=j.get("url", ""),
        location=j.get("location"),
        description=j.get("description", ""),
        tags=tuple(j.get("tags") or ()),
        salary=j.get("salary"),
        posted_at=posted_at,
        raw=j.get("raw") or {},
    )
    q = item.get("query") or None
    query = SearchQuery(text=q.get("text", "")) if isinstance(q, dict) else None
    return JobMatch(
        job=job,
        score=item.get("score", 0.0),
        matched_terms=tuple(item.get("matched_terms") or ()),
        query=query,
        rationale=item.get("rationale", ""),
    )


def render_html(
    profile: UserProfile,
    matches: list[JobMatch],
    *,
    source_errors=(),
    questions=(),
    generated_at: datetime | None = None,
) -> str:
    """Render a self-contained HTML page of ranked jobs.

    The page is a single file with inline CSS/JS and no external requests, so
    it opens straight from disk. Each job is a card with score, apply button,
    matched-term chips, and a one-click-copy outreach message.
    """

    stamp = (generated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    sources = sorted({match.job.source for match in matches})
    title = f"Job matches for {profile.name}" if profile.name else "Job matches"
    summary = f"{len(matches)} ranked job{'s' if len(matches) != 1 else ''}"
    if sources:
        summary += f" across {len(sources)} source{'s' if len(sources) != 1 else ''}"

    cards = "\n".join(_render_card(index, match, profile) for index, match in enumerate(matches, start=1))
    if not matches:
        cards = '<p class="empty">No matches found. Try broadening the sources or relaxing preferences.</p>'

    errors_html = ""
    error_list = list(source_errors)
    if error_list:
        items = "".join(f"<li>{escape(str(err))}</li>" for err in error_list[:10])
        errors_html = f'<details class="errors"><summary>Source warnings ({len(error_list)})</summary><ul>{items}</ul></details>'

    return _TEMPLATE.format(
        title=escape(title),
        headline=escape(profile.headline or ""),
        summary=escape(summary),
        stamp=escape(stamp),
        sources=escape(", ".join(sources) or "—"),
        cards=cards,
        errors=errors_html,
    )


def _render_card(index: int, match: JobMatch, profile: UserProfile) -> str:
    job = match.job
    apply_url = resolve_apply_url(match)
    message = build_outreach_message(profile, match)
    chips = "".join(f'<span class="chip">{escape(term)}</span>' for term in match.matched_terms[:10])
    meta_bits = []
    if job.location:
        meta_bits.append(f'<span class="meta">📍 {escape(job.location)}</span>')
    if job.salary:
        meta_bits.append(f'<span class="meta">💰 {escape(job.salary)}</span>')
    if job.posted_at:
        meta_bits.append(f'<span class="meta">🗓 {escape(job.posted_at.strftime("%Y-%m-%d"))}</span>')
    meta = "".join(meta_bits)

    posting_link = ""
    if job.url and job.url != apply_url:
        posting_link = f'<a class="btn btn-ghost" href="{escape(job.url)}" target="_blank" rel="noopener">View posting</a>'
    apply_button = ""
    if apply_url:
        apply_button = f'<a class="btn btn-apply" href="{escape(apply_url)}" target="_blank" rel="noopener">Apply ↗</a>'

    # filter haystack lets the search box match title/company/source.
    haystack = escape(" ".join((job.title, job.company, job.source)).lower())

    return f"""    <article class="card" data-search="{haystack}">
      <div class="card-head">
        <span class="rank">#{index}</span>
        <span class="score" title="match score">{match.score:g}</span>
        <span class="source">{escape(job.source)}</span>
      </div>
      <h2 class="title">{escape(job.title)}</h2>
      <div class="company">{escape(job.company)}</div>
      <div class="metarow">{meta}</div>
      <div class="chips">{chips}</div>
      <p class="rationale">{escape(match.rationale)}</p>
      <div class="actions">{apply_button}{posting_link}</div>
      <div class="outreach">
        <div class="outreach-head">
          <span>Outreach message</span>
          <button class="btn btn-copy" type="button" onclick="copyMsg(this)">Copy</button>
        </div>
        <p class="msg">{escape(message)}</p>
      </div>
    </article>"""


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{
    --bg: #f6f7f9; --fg: #1b1f24; --muted: #5c6773; --card: #ffffff;
    --line: #e3e7ec; --accent: #2563eb; --accent-fg: #ffffff; --chip: #eef2f7;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f1216; --fg: #e6e9ee; --muted: #9aa4b2; --card: #181c22;
      --line: #2a2f37; --accent: #3b82f6; --accent-fg: #ffffff; --chip: #232932;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  header {{ padding: 28px 20px 16px; max-width: 1100px; margin: 0 auto; }}
  h1 {{ margin: 0 0 4px; font-size: 24px; }}
  .sub {{ color: var(--muted); font-size: 14px; }}
  .toolbar {{ max-width: 1100px; margin: 0 auto; padding: 0 20px 16px; }}
  #filter {{ width: 100%; max-width: 380px; padding: 9px 12px; border: 1px solid var(--line);
    border-radius: 8px; background: var(--card); color: var(--fg); font-size: 14px; }}
  main {{ max-width: 1100px; margin: 0 auto; padding: 0 20px 48px;
    display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 16px; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 12px;
    padding: 16px; display: flex; flex-direction: column; gap: 8px; }}
  .card-head {{ display: flex; align-items: center; gap: 8px; }}
  .rank {{ font-weight: 700; color: var(--muted); font-size: 13px; }}
  .score {{ font-weight: 700; color: var(--accent); font-variant-numeric: tabular-nums; }}
  .source {{ margin-left: auto; font-size: 12px; color: var(--muted);
    background: var(--chip); padding: 2px 8px; border-radius: 999px; }}
  .title {{ margin: 2px 0 0; font-size: 17px; line-height: 1.3; }}
  .company {{ color: var(--muted); font-weight: 600; }}
  .metarow {{ display: flex; flex-wrap: wrap; gap: 10px; font-size: 13px; color: var(--muted); }}
  .chips {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .chip {{ font-size: 11px; background: var(--chip); color: var(--muted);
    padding: 2px 8px; border-radius: 999px; }}
  .rationale {{ font-size: 13px; color: var(--muted); margin: 4px 0 0; }}
  .actions {{ display: flex; gap: 8px; margin-top: 4px; }}
  .btn {{ font-size: 13px; font-weight: 600; text-decoration: none; padding: 8px 14px;
    border-radius: 8px; border: 1px solid var(--line); cursor: pointer; background: var(--card);
    color: var(--fg); display: inline-flex; align-items: center; }}
  .btn-apply {{ background: var(--accent); color: var(--accent-fg); border-color: var(--accent); }}
  .btn-ghost {{ background: transparent; }}
  .outreach {{ margin-top: 6px; border-top: 1px solid var(--line); padding-top: 10px; }}
  .outreach-head {{ display: flex; align-items: center; justify-content: space-between;
    font-size: 12px; color: var(--muted); margin-bottom: 4px; }}
  .btn-copy {{ padding: 3px 10px; font-size: 12px; }}
  .msg {{ font-size: 13px; margin: 0; white-space: pre-wrap; }}
  .empty {{ grid-column: 1 / -1; color: var(--muted); text-align: center; padding: 40px; }}
  .errors {{ max-width: 1100px; margin: 0 auto 40px; padding: 0 20px; color: var(--muted); font-size: 13px; }}
  footer {{ max-width: 1100px; margin: 0 auto; padding: 0 20px 40px; color: var(--muted); font-size: 12px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="sub">{headline}</div>
  <div class="sub">{summary} · generated {stamp}</div>
</header>
<div class="toolbar">
  <input id="filter" type="search" placeholder="Filter by title, company, or source…" oninput="filterCards(this.value)">
</div>
<main id="cards">
{cards}
</main>
{errors}
<footer>Sources: {sources}. Generated by the job-hunting skill. Verify each posting is still open before applying.</footer>
<script>
  function copyMsg(btn) {{
    var msg = btn.closest('.outreach').querySelector('.msg').innerText;
    var done = function () {{ var t = btn.textContent; btn.textContent = 'Copied'; setTimeout(function () {{ btn.textContent = t; }}, 1200); }};
    if (navigator.clipboard && navigator.clipboard.writeText) {{ navigator.clipboard.writeText(msg).then(done, done); }}
    else {{ var ta = document.createElement('textarea'); ta.value = msg; document.body.appendChild(ta); ta.select();
      try {{ document.execCommand('copy'); }} catch (e) {{}} document.body.removeChild(ta); done(); }}
  }}
  function filterCards(q) {{
    q = q.trim().toLowerCase();
    document.querySelectorAll('.card').forEach(function (c) {{
      c.style.display = !q || c.getAttribute('data-search').indexOf(q) !== -1 ? '' : 'none';
    }});
  }}
</script>
</body>
</html>
"""
