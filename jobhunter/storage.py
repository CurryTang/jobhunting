from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from jobhunter.models import JobMatch, JobPosting, UserProfile


@dataclass(frozen=True)
class StoreSummary:
    """Counts for one persisted search run."""

    run_id: int
    jobs_seen: int
    jobs_inserted: int
    jobs_updated: int
    matches_inserted: int


@dataclass(frozen=True)
class SourceFetchSummary:
    """Counts for one progressive source fetch."""

    source_query_id: int
    fetch_run_id: int
    jobs_seen: int
    source_items_inserted: int
    source_items_updated: int
    jobs_inserted: int
    jobs_updated: int
    observations_inserted: int


class SQLiteJobStore:
    """Persist normalized jobs and search-run matches with deterministic dedupe."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save_search_run(
        self,
        *,
        input_ref: str,
        profile: UserProfile,
        sources: Iterable[str],
        matches: list[JobMatch],
        source_errors: Iterable[str] = (),
        record_jobs: bool = True,
    ) -> StoreSummary:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            _initialize_schema(conn)
            now = _utc_now()
            run_id = _insert_search_run(
                conn,
                input_ref=input_ref,
                profile=profile,
                sources=tuple(sources),
                source_errors=tuple(source_errors),
                now=now,
            )
            inserted = 0
            updated = 0
            matches_inserted = 0
            for rank, match in enumerate(matches, start=1):
                if record_jobs:
                    outcome = _upsert_job(conn, match.job, now=now)
                    inserted += 1 if outcome == "inserted" else 0
                    updated += 1 if outcome == "updated" else 0
                matches_inserted += _insert_match(conn, run_id=run_id, rank=rank, match=match)
            return StoreSummary(
                run_id=run_id,
                jobs_seen=len(matches),
                jobs_inserted=inserted,
                jobs_updated=updated,
                matches_inserted=matches_inserted,
            )

    def has_fresh_source_query(self, source: str, query_text: str, *, max_age_hours: int = 24) -> bool:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            _initialize_schema(conn)
            row = conn.execute(
                """
                SELECT last_fetched_at FROM source_queries
                WHERE source = ? AND query_hash = ? AND last_fetched_at IS NOT NULL
                """,
                (source, _query_hash(query_text)),
            ).fetchone()
        if row is None:
            return False
        return _is_recent(row["last_fetched_at"], max_age_hours=max_age_hours)

    def list_cached_jobs(self, *, sources: Iterable[str] = (), limit: int = 1000) -> list[JobPosting]:
        source_values = tuple(sources)
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            _initialize_schema(conn)
            if source_values:
                placeholders = ",".join("?" for _ in source_values)
                rows = conn.execute(
                    f"""
                    SELECT * FROM jobs
                    WHERE source IN ({placeholders})
                    ORDER BY last_seen_at DESC
                    LIMIT ?
                    """,
                    (*source_values, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM jobs ORDER BY last_seen_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [_job_from_row(row) for row in rows]

    def save_source_fetch(
        self,
        *,
        source: str,
        query_text: str,
        jobs: list[JobPosting],
        role_family: str | None = None,
        location: str | None = None,
        filters: dict[str, Any] | None = None,
        request: dict[str, Any] | None = None,
        cursor: str | None = None,
        status: str = "ok",
        error: str | None = None,
    ) -> SourceFetchSummary:
        with sqlite3.connect(self.path) as conn:
            conn.row_factory = sqlite3.Row
            _initialize_schema(conn)
            now = _utc_now()
            source_query_id = _upsert_source_query(
                conn,
                source=source,
                query_text=query_text,
                role_family=role_family,
                location=location,
                filters=filters or {},
                now=now,
            )
            fetch_run_id = _insert_fetch_run(
                conn,
                source_query_id=source_query_id,
                source=source,
                request=request or {},
                cursor=cursor,
                status=status,
                error=error,
                now=now,
            )
            source_inserted = 0
            source_updated = 0
            jobs_inserted = 0
            jobs_updated = 0
            observations_inserted = 0
            for rank, job in enumerate(jobs, start=1):
                source_item_key, source_outcome = _upsert_source_item(conn, job, now=now)
                source_inserted += 1 if source_outcome == "inserted" else 0
                source_updated += 1 if source_outcome == "updated" else 0
                job_outcome = _upsert_job(conn, job, now=now)
                jobs_inserted += 1 if job_outcome == "inserted" else 0
                jobs_updated += 1 if job_outcome == "updated" else 0
                observations_inserted += _insert_job_observation(
                    conn,
                    job_key_value=job_key(job),
                    source_item_key=source_item_key,
                    fetch_run_id=fetch_run_id,
                    source=source,
                    source_rank=rank,
                    matched_query_text=query_text,
                    now=now,
                )
            _finish_fetch_run(
                conn,
                fetch_run_id=fetch_run_id,
                items_seen=len(jobs),
                items_new=source_inserted,
                items_updated=source_updated,
                now=now,
            )
            if status != "ok":
                _clear_source_query_freshness(conn, source_query_id=source_query_id)
            return SourceFetchSummary(
                source_query_id=source_query_id,
                fetch_run_id=fetch_run_id,
                jobs_seen=len(jobs),
                source_items_inserted=source_inserted,
                source_items_updated=source_updated,
                jobs_inserted=jobs_inserted,
                jobs_updated=jobs_updated,
                observations_inserted=observations_inserted,
            )


class PostgresJobStore:
    """Persist jobs to a Postgres-compatible production database."""

    def __init__(self, url: str) -> None:
        self.url = url

    def save_search_run(
        self,
        *,
        input_ref: str,
        profile: UserProfile,
        sources: Iterable[str],
        matches: list[JobMatch],
        source_errors: Iterable[str] = (),
        record_jobs: bool = True,
    ) -> StoreSummary:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - depends on optional production extra.
            raise RuntimeError(
                "Postgres storage requires optional dependency `psycopg`. "
                "Install with `python -m pip install -U '.[postgres]'`."
            ) from exc

        with psycopg.connect(self.url) as conn:
            _initialize_postgres_schema(conn)
            now = _utc_now()
            run_id = _insert_postgres_search_run(
                conn,
                input_ref=input_ref,
                profile=profile,
                sources=tuple(sources),
                source_errors=tuple(source_errors),
                now=now,
            )
            inserted = 0
            updated = 0
            matches_inserted = 0
            for rank, match in enumerate(matches, start=1):
                if record_jobs:
                    outcome = _upsert_postgres_job(conn, match.job, now=now)
                    inserted += 1 if outcome == "inserted" else 0
                    updated += 1 if outcome == "updated" else 0
                matches_inserted += _insert_postgres_match(conn, run_id=run_id, rank=rank, match=match)
            return StoreSummary(
                run_id=run_id,
                jobs_seen=len(matches),
                jobs_inserted=inserted,
                jobs_updated=updated,
                matches_inserted=matches_inserted,
            )

    def has_fresh_source_query(self, source: str, query_text: str, *, max_age_hours: int = 24) -> bool:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Postgres storage requires optional dependency `psycopg`.") from exc
        with psycopg.connect(self.url) as conn:
            _initialize_postgres_schema(conn)
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT last_fetched_at FROM source_queries
                    WHERE source = %s AND query_hash = %s AND last_fetched_at IS NOT NULL
                    """,
                    (source, _query_hash(query_text)),
                )
                row = cursor.fetchone()
        if row is None:
            return False
        return _is_recent(row[0], max_age_hours=max_age_hours)

    def list_cached_jobs(self, *, sources: Iterable[str] = (), limit: int = 1000) -> list[JobPosting]:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Postgres storage requires optional dependency `psycopg`.") from exc
        source_values = tuple(sources)
        with psycopg.connect(self.url) as conn:
            _initialize_postgres_schema(conn)
            with conn.cursor() as cursor:
                if source_values:
                    cursor.execute(
                        """
                        SELECT source, source_id, title, company, url, location, description,
                               tags_json, salary, posted_at, raw_json
                        FROM jobs
                        WHERE source = ANY(%s)
                        ORDER BY last_seen_at DESC
                        LIMIT %s
                        """,
                        (list(source_values), limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT source, source_id, title, company, url, location, description,
                               tags_json, salary, posted_at, raw_json
                        FROM jobs
                        ORDER BY last_seen_at DESC
                        LIMIT %s
                        """,
                        (limit,),
                    )
                rows = cursor.fetchall()
        return [_job_from_tuple(row) for row in rows]

    def save_source_fetch(
        self,
        *,
        source: str,
        query_text: str,
        jobs: list[JobPosting],
        role_family: str | None = None,
        location: str | None = None,
        filters: dict[str, Any] | None = None,
        request: dict[str, Any] | None = None,
        cursor: str | None = None,
        status: str = "ok",
        error: str | None = None,
    ) -> SourceFetchSummary:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Postgres storage requires optional dependency `psycopg`.") from exc
        with psycopg.connect(self.url) as conn:
            _initialize_postgres_schema(conn)
            now = _utc_now()
            source_query_id = _upsert_postgres_source_query(
                conn,
                source=source,
                query_text=query_text,
                role_family=role_family,
                location=location,
                filters=filters or {},
                now=now,
            )
            fetch_run_id = _insert_postgres_fetch_run(
                conn,
                source_query_id=source_query_id,
                source=source,
                request=request or {},
                cursor=cursor,
                status=status,
                error=error,
                now=now,
            )
            source_inserted = 0
            source_updated = 0
            jobs_inserted = 0
            jobs_updated = 0
            observations_inserted = 0
            for rank, job in enumerate(jobs, start=1):
                source_item_key, source_outcome = _upsert_postgres_source_item(conn, job, now=now)
                source_inserted += 1 if source_outcome == "inserted" else 0
                source_updated += 1 if source_outcome == "updated" else 0
                job_outcome = _upsert_postgres_job(conn, job, now=now)
                jobs_inserted += 1 if job_outcome == "inserted" else 0
                jobs_updated += 1 if job_outcome == "updated" else 0
                observations_inserted += _insert_postgres_job_observation(
                    conn,
                    job_key_value=job_key(job),
                    source_item_key=source_item_key,
                    fetch_run_id=fetch_run_id,
                    source=source,
                    source_rank=rank,
                    matched_query_text=query_text,
                    now=now,
                )
            _finish_postgres_fetch_run(
                conn,
                fetch_run_id=fetch_run_id,
                items_seen=len(jobs),
                items_new=source_inserted,
                items_updated=source_updated,
                now=now,
            )
            if status != "ok":
                _clear_postgres_source_query_freshness(conn, source_query_id=source_query_id)
            return SourceFetchSummary(
                source_query_id=source_query_id,
                fetch_run_id=fetch_run_id,
                jobs_seen=len(jobs),
                source_items_inserted=source_inserted,
                source_items_updated=source_updated,
                jobs_inserted=jobs_inserted,
                jobs_updated=jobs_updated,
                observations_inserted=observations_inserted,
            )


def create_job_store(url: str):
    """Create a job store from a database URL."""

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme in {"postgres", "postgresql"}:
        return PostgresJobStore(url)
    if parsed.scheme == "sqlite":
        if parsed.netloc and parsed.netloc != "localhost":
            raise ValueError("sqlite URLs must be local paths such as sqlite:///tmp/jobs.sqlite")
        return SQLiteJobStore(urllib.parse.unquote(parsed.path))
    raise ValueError("unsupported store URL scheme; use postgresql://... for production")


def job_key(job: JobPosting) -> str:
    """Create a stable dedupe key for a job posting across repeated searches."""

    logical = _logical_job_identity(job)
    if logical:
        return _digest(f"logical:{logical}")
    canonical_url = _canonical_url(job.url)
    if canonical_url:
        return _digest(f"url:{canonical_url}")
    if job.source_id:
        return _digest(f"source:{_norm(job.source)}:{_norm(job.source_id)}")
    fallback = "|".join(_norm(part) for part in (job.company, job.title, job.location or ""))
    return _digest(f"fallback:{fallback}")


def _logical_job_identity(job: JobPosting) -> str:
    company = _norm_company(job.company)
    title = _norm_title(job.title)
    if not company or not title:
        return ""
    location = _norm_location(job.location or "")
    return "|".join(part for part in (company, title, location) if part)


def _initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE IF NOT EXISTS jobs (
            job_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_id TEXT,
            title TEXT NOT NULL,
            company TEXT NOT NULL,
            url TEXT NOT NULL,
            canonical_url TEXT,
            location TEXT,
            description TEXT,
            tags_json TEXT NOT NULL,
            salary TEXT,
            posted_at TEXT,
            raw_json TEXT NOT NULL,
            detail_text TEXT,
            detail_content_hash TEXT,
            detail_fetched_at TEXT,
            content_hash TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company);
        CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
        CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at ON jobs(last_seen_at);

        CREATE TABLE IF NOT EXISTS source_queries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            query_text TEXT NOT NULL,
            normalized_query TEXT NOT NULL,
            role_family TEXT,
            location TEXT,
            filters_json TEXT NOT NULL,
            query_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_fetched_at TEXT,
            fetch_count INTEGER NOT NULL DEFAULT 0,
            UNIQUE(source, query_hash)
        );

        CREATE INDEX IF NOT EXISTS idx_source_queries_source ON source_queries(source);
        CREATE INDEX IF NOT EXISTS idx_source_queries_last_fetched_at ON source_queries(last_fetched_at);

        CREATE TABLE IF NOT EXISTS fetch_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_query_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            request_json TEXT NOT NULL,
            cursor TEXT,
            status TEXT NOT NULL,
            items_seen INTEGER NOT NULL DEFAULT 0,
            items_new INTEGER NOT NULL DEFAULT 0,
            items_updated INTEGER NOT NULL DEFAULT 0,
            error TEXT,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY (source_query_id) REFERENCES source_queries(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_fetch_runs_source_query ON fetch_runs(source_query_id);
        CREATE INDEX IF NOT EXISTS idx_fetch_runs_started_at ON fetch_runs(started_at);

        CREATE TABLE IF NOT EXISTS source_items (
            source_item_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_item_id TEXT,
            source_url TEXT,
            canonical_url TEXT,
            title TEXT,
            company TEXT,
            location TEXT,
            raw_json TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            first_seen_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            seen_count INTEGER NOT NULL DEFAULT 1
        );

        CREATE INDEX IF NOT EXISTS idx_source_items_source ON source_items(source);
        CREATE INDEX IF NOT EXISTS idx_source_items_canonical_url ON source_items(canonical_url);
        CREATE INDEX IF NOT EXISTS idx_source_items_last_seen_at ON source_items(last_seen_at);

        CREATE TABLE IF NOT EXISTS job_observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_key TEXT NOT NULL,
            source_item_key TEXT NOT NULL,
            fetch_run_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            source_rank INTEGER,
            matched_query_text TEXT,
            UNIQUE(job_key, source_item_key, fetch_run_id),
            FOREIGN KEY (job_key) REFERENCES jobs(job_key) ON DELETE CASCADE,
            FOREIGN KEY (source_item_key) REFERENCES source_items(source_item_key) ON DELETE CASCADE,
            FOREIGN KEY (fetch_run_id) REFERENCES fetch_runs(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_job_observations_job ON job_observations(job_key);
        CREATE INDEX IF NOT EXISTS idx_job_observations_source ON job_observations(source);

        CREATE TABLE IF NOT EXISTS search_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            input_ref TEXT NOT NULL,
            profile_name TEXT,
            profile_headline TEXT,
            profile_json TEXT NOT NULL,
            preferences_json TEXT NOT NULL,
            sources_json TEXT NOT NULL,
            source_errors_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS job_matches (
            run_id INTEGER NOT NULL,
            job_key TEXT NOT NULL,
            rank INTEGER NOT NULL,
            score REAL NOT NULL,
            matched_terms_json TEXT NOT NULL,
            query_json TEXT NOT NULL,
            rationale TEXT NOT NULL,
            PRIMARY KEY (run_id, job_key),
            FOREIGN KEY (run_id) REFERENCES search_runs(id) ON DELETE CASCADE,
            FOREIGN KEY (job_key) REFERENCES jobs(job_key) ON DELETE CASCADE
        );
        """
    )
    _ensure_sqlite_column(conn, "source_items", "detail_text", "TEXT")
    _ensure_sqlite_column(conn, "source_items", "detail_content_hash", "TEXT")
    _ensure_sqlite_column(conn, "source_items", "detail_fetched_at", "TEXT")


def _initialize_postgres_schema(conn) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                job_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_id TEXT,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                url TEXT NOT NULL,
                canonical_url TEXT,
                location TEXT,
                description TEXT,
                tags_json JSONB NOT NULL,
                salary TEXT,
                posted_at TEXT,
                raw_json JSONB NOT NULL,
                detail_text TEXT,
                detail_content_hash TEXT,
                detail_fetched_at TIMESTAMPTZ,
                content_hash TEXT NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL,
                last_seen_at TIMESTAMPTZ NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_last_seen_at ON jobs(last_seen_at)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS source_queries (
                id BIGSERIAL PRIMARY KEY,
                source TEXT NOT NULL,
                query_text TEXT NOT NULL,
                normalized_query TEXT NOT NULL,
                role_family TEXT,
                location TEXT,
                filters_json JSONB NOT NULL,
                query_hash TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL,
                last_fetched_at TIMESTAMPTZ,
                fetch_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(source, query_hash)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_queries_source ON source_queries(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_queries_last_fetched_at ON source_queries(last_fetched_at)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS fetch_runs (
                id BIGSERIAL PRIMARY KEY,
                source_query_id BIGINT NOT NULL REFERENCES source_queries(id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                request_json JSONB NOT NULL,
                cursor TEXT,
                status TEXT NOT NULL,
                items_seen INTEGER NOT NULL DEFAULT 0,
                items_new INTEGER NOT NULL DEFAULT 0,
                items_updated INTEGER NOT NULL DEFAULT 0,
                error TEXT,
                started_at TIMESTAMPTZ NOT NULL,
                finished_at TIMESTAMPTZ
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fetch_runs_source_query ON fetch_runs(source_query_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_fetch_runs_started_at ON fetch_runs(started_at)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS source_items (
                source_item_key TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                source_item_id TEXT,
                source_url TEXT,
                canonical_url TEXT,
                title TEXT,
                company TEXT,
                location TEXT,
                raw_json JSONB NOT NULL,
                content_hash TEXT NOT NULL,
                first_seen_at TIMESTAMPTZ NOT NULL,
                last_seen_at TIMESTAMPTZ NOT NULL,
                seen_count INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_items_source ON source_items(source)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_items_canonical_url ON source_items(canonical_url)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_source_items_last_seen_at ON source_items(last_seen_at)")
        cursor.execute("ALTER TABLE source_items ADD COLUMN IF NOT EXISTS detail_text TEXT")
        cursor.execute("ALTER TABLE source_items ADD COLUMN IF NOT EXISTS detail_content_hash TEXT")
        cursor.execute("ALTER TABLE source_items ADD COLUMN IF NOT EXISTS detail_fetched_at TIMESTAMPTZ")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS job_observations (
                id BIGSERIAL PRIMARY KEY,
                job_key TEXT NOT NULL REFERENCES jobs(job_key) ON DELETE CASCADE,
                source_item_key TEXT NOT NULL REFERENCES source_items(source_item_key) ON DELETE CASCADE,
                fetch_run_id BIGINT NOT NULL REFERENCES fetch_runs(id) ON DELETE CASCADE,
                source TEXT NOT NULL,
                observed_at TIMESTAMPTZ NOT NULL,
                source_rank INTEGER,
                matched_query_text TEXT,
                UNIQUE(job_key, source_item_key, fetch_run_id)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_observations_job ON job_observations(job_key)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_observations_source ON job_observations(source)")
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS search_runs (
                id BIGSERIAL PRIMARY KEY,
                input_ref TEXT NOT NULL,
                profile_name TEXT,
                profile_headline TEXT,
                profile_json JSONB NOT NULL,
                preferences_json JSONB NOT NULL,
                sources_json JSONB NOT NULL,
                source_errors_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS job_matches (
                run_id BIGINT NOT NULL REFERENCES search_runs(id) ON DELETE CASCADE,
                job_key TEXT NOT NULL REFERENCES jobs(job_key) ON DELETE CASCADE,
                rank INTEGER NOT NULL,
                score DOUBLE PRECISION NOT NULL,
                matched_terms_json JSONB NOT NULL,
                query_json JSONB NOT NULL,
                rationale TEXT NOT NULL,
                PRIMARY KEY (run_id, job_key)
            )
            """
        )


def _ensure_sqlite_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _insert_search_run(
    conn: sqlite3.Connection,
    *,
    input_ref: str,
    profile: UserProfile,
    sources: tuple[str, ...],
    source_errors: tuple[str, ...],
    now: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO search_runs (
            input_ref, profile_name, profile_headline, profile_json,
            preferences_json, sources_json, source_errors_json, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            input_ref,
            profile.name,
            profile.headline,
            _json_dumps(asdict(profile)),
            _json_dumps(asdict(profile.preferences)),
            _json_dumps(sources),
            _json_dumps(source_errors),
            now,
        ),
    )
    return int(cursor.lastrowid)


def _insert_postgres_search_run(
    conn,
    *,
    input_ref: str,
    profile: UserProfile,
    sources: tuple[str, ...],
    source_errors: tuple[str, ...],
    now: str,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO search_runs (
                input_ref, profile_name, profile_headline, profile_json,
                preferences_json, sources_json, source_errors_json, created_at
            )
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb, %s)
            RETURNING id
            """,
            (
                input_ref,
                profile.name,
                profile.headline,
                _json_dumps(asdict(profile)),
                _json_dumps(asdict(profile.preferences)),
                _json_dumps(sources),
                _json_dumps(source_errors),
                now,
            ),
        )
        row = cursor.fetchone()
    return int(row[0])


def _upsert_source_query(
    conn: sqlite3.Connection,
    *,
    source: str,
    query_text: str,
    role_family: str | None,
    location: str | None,
    filters: dict[str, Any],
    now: str,
) -> int:
    q_hash = _query_hash(query_text)
    conn.execute(
        """
        INSERT INTO source_queries (
            source, query_text, normalized_query, role_family, location,
            filters_json, query_hash, created_at, last_fetched_at, fetch_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(source, query_hash) DO UPDATE SET
            query_text = excluded.query_text,
            normalized_query = excluded.normalized_query,
            role_family = excluded.role_family,
            location = excluded.location,
            filters_json = excluded.filters_json,
            last_fetched_at = excluded.last_fetched_at,
            fetch_count = source_queries.fetch_count + 1
        """,
        (
            source,
            query_text,
            _norm(query_text),
            role_family,
            location,
            _json_dumps(filters),
            q_hash,
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT id FROM source_queries WHERE source = ? AND query_hash = ?",
        (source, q_hash),
    ).fetchone()
    return int(row["id"])


def _upsert_postgres_source_query(
    conn,
    *,
    source: str,
    query_text: str,
    role_family: str | None,
    location: str | None,
    filters: dict[str, Any],
    now: str,
) -> int:
    q_hash = _query_hash(query_text)
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO source_queries (
                source, query_text, normalized_query, role_family, location,
                filters_json, query_hash, created_at, last_fetched_at, fetch_count
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, 1)
            ON CONFLICT(source, query_hash) DO UPDATE SET
                query_text = excluded.query_text,
                normalized_query = excluded.normalized_query,
                role_family = excluded.role_family,
                location = excluded.location,
                filters_json = excluded.filters_json,
                last_fetched_at = excluded.last_fetched_at,
                fetch_count = source_queries.fetch_count + 1
            RETURNING id
            """,
            (
                source,
                query_text,
                _norm(query_text),
                role_family,
                location,
                _json_dumps(filters),
                q_hash,
                now,
                now,
            ),
        )
        row = cursor.fetchone()
    return int(row[0])


def _insert_fetch_run(
    conn: sqlite3.Connection,
    *,
    source_query_id: int,
    source: str,
    request: dict[str, Any],
    cursor: str | None,
    status: str,
    error: str | None,
    now: str,
) -> int:
    db_cursor = conn.execute(
        """
        INSERT INTO fetch_runs (
            source_query_id, source, request_json, cursor, status, error, started_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (source_query_id, source, _json_dumps(request), cursor, status, error, now),
    )
    return int(db_cursor.lastrowid)


def _insert_postgres_fetch_run(
    conn,
    *,
    source_query_id: int,
    source: str,
    request: dict[str, Any],
    cursor: str | None,
    status: str,
    error: str | None,
    now: str,
) -> int:
    with conn.cursor() as cursor_obj:
        cursor_obj.execute(
            """
            INSERT INTO fetch_runs (
                source_query_id, source, request_json, cursor, status, error, started_at
            )
            VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s)
            RETURNING id
            """,
            (source_query_id, source, _json_dumps(request), cursor, status, error, now),
        )
        row = cursor_obj.fetchone()
    return int(row[0])


def _finish_fetch_run(
    conn: sqlite3.Connection,
    *,
    fetch_run_id: int,
    items_seen: int,
    items_new: int,
    items_updated: int,
    now: str,
) -> None:
    conn.execute(
        """
        UPDATE fetch_runs
        SET items_seen = ?, items_new = ?, items_updated = ?, finished_at = ?
        WHERE id = ?
        """,
        (items_seen, items_new, items_updated, now, fetch_run_id),
    )


def _finish_postgres_fetch_run(
    conn,
    *,
    fetch_run_id: int,
    items_seen: int,
    items_new: int,
    items_updated: int,
    now: str,
) -> None:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            UPDATE fetch_runs
            SET items_seen = %s, items_new = %s, items_updated = %s, finished_at = %s
            WHERE id = %s
            """,
            (items_seen, items_new, items_updated, now, fetch_run_id),
        )


def _clear_source_query_freshness(conn: sqlite3.Connection, *, source_query_id: int) -> None:
    conn.execute("UPDATE source_queries SET last_fetched_at = NULL WHERE id = ?", (source_query_id,))


def _clear_postgres_source_query_freshness(conn, *, source_query_id: int) -> None:
    with conn.cursor() as cursor:
        cursor.execute("UPDATE source_queries SET last_fetched_at = NULL WHERE id = %s", (source_query_id,))


def _upsert_job(conn: sqlite3.Connection, job: JobPosting, *, now: str) -> str:
    key = job_key(job)
    exists = conn.execute("SELECT 1 FROM jobs WHERE job_key = ?", (key,)).fetchone() is not None
    conn.execute(
        """
        INSERT INTO jobs (
            job_key, source, source_id, title, company, url, canonical_url,
            location, description, tags_json, salary, posted_at, raw_json,
            content_hash, first_seen_at, last_seen_at, seen_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(job_key) DO UPDATE SET
            source = excluded.source,
            source_id = excluded.source_id,
            title = excluded.title,
            company = excluded.company,
            url = excluded.url,
            canonical_url = excluded.canonical_url,
            location = excluded.location,
            description = excluded.description,
            tags_json = excluded.tags_json,
            salary = excluded.salary,
            posted_at = excluded.posted_at,
            raw_json = excluded.raw_json,
            content_hash = excluded.content_hash,
            last_seen_at = excluded.last_seen_at,
            seen_count = jobs.seen_count + 1
        """,
        (
            key,
            job.source,
            job.source_id,
            job.title,
            job.company,
            job.url,
            _canonical_url(job.url),
            job.location,
            job.description,
            _json_dumps(job.tags),
            job.salary,
            job.posted_at.isoformat() if job.posted_at else None,
            _json_dumps(job.raw),
            _content_hash(job),
            now,
            now,
        ),
    )
    return "updated" if exists else "inserted"


def _upsert_postgres_job(conn, job: JobPosting, *, now: str) -> str:
    key = job_key(job)
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM jobs WHERE job_key = %s", (key,))
        exists = cursor.fetchone() is not None
        cursor.execute(
            """
            INSERT INTO jobs (
                job_key, source, source_id, title, company, url, canonical_url,
                location, description, tags_json, salary, posted_at, raw_json,
                content_hash, first_seen_at, last_seen_at, seen_count
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s,
                %s::jsonb, %s, %s, %s, 1
            )
            ON CONFLICT(job_key) DO UPDATE SET
                source = excluded.source,
                source_id = excluded.source_id,
                title = excluded.title,
                company = excluded.company,
                url = excluded.url,
                canonical_url = excluded.canonical_url,
                location = excluded.location,
                description = excluded.description,
                tags_json = excluded.tags_json,
                salary = excluded.salary,
                posted_at = excluded.posted_at,
                raw_json = excluded.raw_json,
                content_hash = excluded.content_hash,
                last_seen_at = excluded.last_seen_at,
                seen_count = jobs.seen_count + 1
            """,
            (
                key,
                job.source,
                job.source_id,
                job.title,
                job.company,
                job.url,
                _canonical_url(job.url),
                job.location,
                job.description,
                _json_dumps(job.tags),
                job.salary,
                job.posted_at.isoformat() if job.posted_at else None,
                _json_dumps(job.raw),
                _content_hash(job),
                now,
                now,
            ),
        )
    return "updated" if exists else "inserted"


def _insert_match(conn: sqlite3.Connection, *, run_id: int, rank: int, match: JobMatch) -> int:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO job_matches (
            run_id, job_key, rank, score, matched_terms_json, query_json, rationale
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            job_key(match.job),
            rank,
            match.score,
            _json_dumps(match.matched_terms),
            _json_dumps(asdict(match.query) if match.query else None),
            match.rationale,
        ),
    )
    return int(cursor.rowcount)


def _insert_postgres_match(conn, *, run_id: int, rank: int, match: JobMatch) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO job_matches (
                run_id, job_key, rank, score, matched_terms_json, query_json, rationale
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
            ON CONFLICT (run_id, job_key) DO NOTHING
            """,
            (
                run_id,
                job_key(match.job),
                rank,
                match.score,
                _json_dumps(match.matched_terms),
                _json_dumps(asdict(match.query) if match.query else None),
                match.rationale,
            ),
        )
        return int(cursor.rowcount)


def _upsert_source_item(conn: sqlite3.Connection, job: JobPosting, *, now: str) -> tuple[str, str]:
    key = source_item_key(job)
    exists = conn.execute("SELECT 1 FROM source_items WHERE source_item_key = ?", (key,)).fetchone() is not None
    detail_text = _detail_text(job)
    conn.execute(
        """
        INSERT INTO source_items (
            source_item_key, source, source_item_id, source_url, canonical_url,
            title, company, location, raw_json, detail_text, detail_content_hash, detail_fetched_at, content_hash,
            first_seen_at, last_seen_at, seen_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(source_item_key) DO UPDATE SET
            source = excluded.source,
            source_item_id = excluded.source_item_id,
            source_url = excluded.source_url,
            canonical_url = excluded.canonical_url,
            title = excluded.title,
            company = excluded.company,
            location = excluded.location,
            raw_json = excluded.raw_json,
            detail_text = COALESCE(excluded.detail_text, source_items.detail_text),
            detail_content_hash = COALESCE(excluded.detail_content_hash, source_items.detail_content_hash),
            detail_fetched_at = COALESCE(excluded.detail_fetched_at, source_items.detail_fetched_at),
            content_hash = excluded.content_hash,
            last_seen_at = excluded.last_seen_at,
            seen_count = source_items.seen_count + 1
        """,
        (
            key,
            job.source,
            job.source_id,
            job.url,
            _canonical_url(job.url),
            job.title,
            job.company,
            job.location,
            _json_dumps(job.raw),
            detail_text,
            _digest(detail_text) if detail_text else None,
            now if detail_text else None,
            _content_hash(job),
            now,
            now,
        ),
    )
    return key, "updated" if exists else "inserted"


def _upsert_postgres_source_item(conn, job: JobPosting, *, now: str) -> tuple[str, str]:
    key = source_item_key(job)
    detail_text = _detail_text(job)
    with conn.cursor() as cursor:
        cursor.execute("SELECT 1 FROM source_items WHERE source_item_key = %s", (key,))
        exists = cursor.fetchone() is not None
        cursor.execute(
            """
            INSERT INTO source_items (
                source_item_key, source, source_item_id, source_url, canonical_url,
                title, company, location, raw_json, detail_text, detail_content_hash, detail_fetched_at, content_hash,
                first_seen_at, last_seen_at, seen_count
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, 1)
            ON CONFLICT(source_item_key) DO UPDATE SET
                source = excluded.source,
                source_item_id = excluded.source_item_id,
                source_url = excluded.source_url,
                canonical_url = excluded.canonical_url,
                title = excluded.title,
                company = excluded.company,
                location = excluded.location,
                raw_json = excluded.raw_json,
                detail_text = COALESCE(excluded.detail_text, source_items.detail_text),
                detail_content_hash = COALESCE(excluded.detail_content_hash, source_items.detail_content_hash),
                detail_fetched_at = COALESCE(excluded.detail_fetched_at, source_items.detail_fetched_at),
                content_hash = excluded.content_hash,
                last_seen_at = excluded.last_seen_at,
                seen_count = source_items.seen_count + 1
            """,
            (
                key,
                job.source,
                job.source_id,
                job.url,
                _canonical_url(job.url),
                job.title,
                job.company,
                job.location,
                _json_dumps(job.raw),
                detail_text,
                _digest(detail_text) if detail_text else None,
                now if detail_text else None,
                _content_hash(job),
                now,
                now,
            ),
        )
    return key, "updated" if exists else "inserted"


def _insert_job_observation(
    conn: sqlite3.Connection,
    *,
    job_key_value: str,
    source_item_key: str,
    fetch_run_id: int,
    source: str,
    source_rank: int,
    matched_query_text: str,
    now: str,
) -> int:
    cursor = conn.execute(
        """
        INSERT OR IGNORE INTO job_observations (
            job_key, source_item_key, fetch_run_id, source, observed_at, source_rank, matched_query_text
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (job_key_value, source_item_key, fetch_run_id, source, now, source_rank, matched_query_text),
    )
    return int(cursor.rowcount)


def _insert_postgres_job_observation(
    conn,
    *,
    job_key_value: str,
    source_item_key: str,
    fetch_run_id: int,
    source: str,
    source_rank: int,
    matched_query_text: str,
    now: str,
) -> int:
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO job_observations (
                job_key, source_item_key, fetch_run_id, source, observed_at, source_rank, matched_query_text
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (job_key, source_item_key, fetch_run_id) DO NOTHING
            """,
            (job_key_value, source_item_key, fetch_run_id, source, now, source_rank, matched_query_text),
        )
        return int(cursor.rowcount)


def source_item_key(job: JobPosting) -> str:
    if job.source_id:
        return _digest(f"source-item:{_norm(job.source)}:{_norm(job.source_id)}")
    canonical = _canonical_url(job.url)
    if canonical:
        return _digest(f"source-url:{_norm(job.source)}:{canonical}")
    fallback = "|".join(_norm(part) for part in (job.source, job.company, job.title, job.location or ""))
    return _digest(f"source-fallback:{fallback}")


def _job_from_row(row: sqlite3.Row) -> JobPosting:
    return JobPosting(
        source=row["source"],
        source_id=row["source_id"] or "",
        title=row["title"],
        company=row["company"],
        url=row["url"],
        location=row["location"],
        description=row["description"] or "",
        tags=tuple(json.loads(row["tags_json"] or "[]")),
        salary=row["salary"],
        posted_at=_parse_datetime(row["posted_at"]),
        raw=json.loads(row["raw_json"] or "{}"),
    )


def _job_from_tuple(row: tuple[Any, ...]) -> JobPosting:
    tags = row[7]
    raw = row[10]
    if isinstance(tags, str):
        tags = json.loads(tags)
    if isinstance(raw, str):
        raw = json.loads(raw)
    return JobPosting(
        source=row[0],
        source_id=row[1] or "",
        title=row[2],
        company=row[3],
        url=row[4],
        location=row[5],
        description=row[6] or "",
        tags=tuple(tags or ()),
        salary=row[8],
        posted_at=_parse_datetime(row[9]),
        raw=raw or {},
    )


def _content_hash(job: JobPosting) -> str:
    content = "|".join(
        _norm(part)
        for part in (
            job.title,
            job.company,
            job.location or "",
            job.description[:2000],
            job.salary or "",
        )
    )
    return _digest(content)


def _detail_text(job: JobPosting) -> str | None:
    value = job.raw.get("detail_text") if isinstance(job.raw, dict) else None
    if not value:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _canonical_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return ""
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    # Drop tracking params and sort the rest so param order never breaks
    # cross-source dedupe. Job-identifying params (e.g. gh_jid) are kept.
    tracking_keys = {"gh_src", "source", "src", "ref", "trk", "lever-source", "lever-origin", "refid", "originalsubdomain"}
    filtered_query = sorted(
        (key, value)
        for key, value in query
        if not key.lower().startswith("utm_") and key.lower() not in tracking_keys
    )
    return urllib.parse.urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            urllib.parse.urlencode(filtered_query),
            "",
        )
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _query_hash(query_text: str) -> str:
    return _digest(_norm(query_text))


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=_json_default)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value.lower()).strip()


def _norm_company(value: str) -> str:
    normalized = _norm(value)
    normalized = re.sub(r"\b(inc|inc\.|llc|ltd|corp|corporation|co|company)\b\.?", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip(" -,.")


def _norm_title(value: str) -> str:
    normalized = _norm(value)
    normalized = re.sub(r"\b(senior|sr|staff|principal|lead|junior|jr|intern|internship|new grad)\b\.?", "", normalized)
    normalized = re.sub(r"\b(i|ii|iii|iv|v|l[1-7])\b", "", normalized)
    normalized = re.sub(r"[-–—|,/]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def _norm_location(value: str) -> str:
    normalized = _norm(value)
    if not normalized:
        return ""
    if any(term in normalized for term in ("remote", "worldwide", "anywhere")):
        return "remote"
    aliases = {
        "new york city": "new york",
        "nyc": "new york",
        "san francisco bay area": "san francisco",
        "bay area": "san francisco",
        "sf": "san francisco",
    }
    for old, new in aliases.items():
        normalized = normalized.replace(old, new)
    normalized = re.sub(r"\b(united states|usa|us|u\\.s\\.|ca|ny|wa|ma|tx|fl|il)\b", "", normalized)
    normalized = re.split(r"\s*/\s*|\s+or\s+|\s*,\s*", normalized)[0]
    return re.sub(r"\s+", " ", normalized).strip(" -,.")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_recent(value: Any, *, max_age_hours: int) -> bool:
    parsed = _parse_datetime(value)
    if parsed is None:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_seconds = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    return age_seconds <= max_age_hours * 3600
