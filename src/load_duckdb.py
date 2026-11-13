"""Load the cleaned parquets into DuckDB.

The loader is idempotent: it creates the database and tables on first run,
then on subsequent runs performs an upsert keyed on ``id`` so re-ingesting a
fresh Overture release updates changed records and inserts new ones without
losing history.

Open places go to ``commercial_places``. Permanently closed places go to
``closed_places`` (recording the release the closure was first seen in) and
are removed from ``commercial_places``. Rows that drop out of Overture are
kept, but their ``last_seen_at`` stops advancing so the map export skips them.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from config import (
    CLEAN_PLACES_PARQUET,
    CLOSED_PLACES_PARQUET,
    DUCKDB_MEMORY_LIMIT,
    DUCKDB_CLOSED_TABLE,
    DUCKDB_PATH,
    DUCKDB_TABLE,
    DUCKDB_THREADS,
    SQL_DIR,
)
from src.transform import OUTPUT_COLUMNS

log = logging.getLogger(__name__)


def _configure(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"SET memory_limit='{DUCKDB_MEMORY_LIMIT}';")
    con.execute(f"SET threads={DUCKDB_THREADS};")
    try:
        con.execute("INSTALL spatial;")
        con.execute("LOAD spatial;")
    except duckdb.Error as err:  # pragma: no cover
        log.warning("spatial extension unavailable: %s", err)
    try:
        con.execute("INSTALL fts;")
        con.execute("LOAD fts;")
    except duckdb.Error as err:  # pragma: no cover
        log.warning("fts extension unavailable: %s", err)


def _apply_schema(con: duckdb.DuckDBPyConnection) -> None:
    schema_path = SQL_DIR / "schema.sql"
    log.info("applying schema from %s", schema_path)
    con.execute(schema_path.read_text())


def _backfill_first_seen(con: duckdb.DuckDBPyConnection) -> None:
    """Populate first_seen_at for rows inserted before the column existed."""
    con.execute(
        f"UPDATE {DUCKDB_TABLE} "
        "SET first_seen_at = ingest_timestamp "
        "WHERE first_seen_at IS NULL;"
    )


def _count_new_ids(con: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    """Rows in the incoming parquet whose id is not yet in the table."""
    row = con.execute(
        f"""
        SELECT COUNT(*) FROM read_parquet('{parquet_path}') p
        WHERE NOT EXISTS (SELECT 1 FROM {DUCKDB_TABLE} c WHERE c.id = p.id);
        """
    ).fetchone()
    return int(row[0]) if row else 0


def _upsert_from_parquet(con: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    """Insert/replace rows from parquet into the target table; returns row count.

    Uses explicit column lists (driven by OUTPUT_COLUMNS) so positional
    SELECT * doesn't break when ALTER TABLE migrations append columns in a
    different order than CREATE TABLE.

    first_seen_at is intentionally absent from the SET clause: on conflict
    the existing value is preserved, so the column reflects the first run in
    which each id appeared.
    """
    cols_str = ", ".join(OUTPUT_COLUMNS)
    update_cols = [c for c in OUTPUT_COLUMNS if c not in {"id", "first_seen_at"}]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    sql = f"""
        INSERT INTO {DUCKDB_TABLE} ({cols_str})
        SELECT {cols_str} FROM read_parquet('{parquet_path}')
        ON CONFLICT (id) DO UPDATE SET {set_clause};
    """
    con.execute(sql)
    return con.execute(f"SELECT COUNT(*) FROM {DUCKDB_TABLE}").fetchone()[0]


def _move_reopened(con: duckdb.DuckDBPyConnection, open_parquet: Path) -> int:
    """Drop ids from closed_places that this release lists as open again."""
    reopened = con.execute(
        f"""
        DELETE FROM {DUCKDB_CLOSED_TABLE}
        WHERE id IN (SELECT id FROM read_parquet('{open_parquet}'));
        """
    ).fetchone()[0]
    if reopened:
        log.info("%d previously closed places are open again", reopened)
    return reopened


def _upsert_closed(con: duckdb.DuckDBPyConnection, closed_parquet: Path) -> int:
    """Upsert permanently closed places and remove them from the open table.

    closed_release / closed_detected_at are set from the run that first saw
    the closure and never overwritten. first_seen_at carries over from
    commercial_places when the place was previously open. Returns the number
    of places newly marked closed in this run.
    """
    newly_closed = con.execute(
        f"""
        SELECT COUNT(*) FROM read_parquet('{closed_parquet}') p
        WHERE NOT EXISTS (SELECT 1 FROM {DUCKDB_CLOSED_TABLE} c WHERE c.id = p.id);
        """
    ).fetchone()[0]

    cols = [c for c in OUTPUT_COLUMNS if c != "first_seen_at"]
    select_cols = ", ".join(f"p.{c}" for c in cols)
    update_cols = [c for c in cols if c != "id"]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    con.execute(
        f"""
        INSERT INTO {DUCKDB_CLOSED_TABLE}
            ({", ".join(cols)}, first_seen_at, closed_release, closed_detected_at)
        SELECT {select_cols},
               COALESCE(o.first_seen_at, p.first_seen_at),
               p.last_seen_release,
               p.last_seen_at
        FROM read_parquet('{closed_parquet}') p
        LEFT JOIN {DUCKDB_TABLE} o ON o.id = p.id
        ON CONFLICT (id) DO UPDATE SET {set_clause};
        """
    )
    moved = con.execute(
        f"""
        DELETE FROM {DUCKDB_TABLE}
        WHERE id IN (SELECT id FROM read_parquet('{closed_parquet}'));
        """
    ).fetchone()[0]
    log.info(
        "closed places: %d newly closed this run, %d moved out of %s",
        newly_closed, moved, DUCKDB_TABLE,
    )
    return newly_closed


def _log_snapshot(con: duckdb.DuckDBPyConnection) -> int:
    """Log current vs. stale row counts; returns rows in the current snapshot."""
    current, stale = con.execute(
        f"""
        SELECT
            COUNT(*) FILTER (last_seen_at = (SELECT MAX(last_seen_at) FROM {DUCKDB_TABLE})),
            COUNT(*) FILTER (last_seen_at IS NULL
                OR last_seen_at < (SELECT MAX(last_seen_at) FROM {DUCKDB_TABLE}))
        FROM {DUCKDB_TABLE};
        """
    ).fetchone()
    closed = con.execute(f"SELECT COUNT(*) FROM {DUCKDB_CLOSED_TABLE}").fetchone()[0]
    log.info(
        "%s: %d current rows, %d stale rows kept for history (not exported); "
        "%s: %d rows",
        DUCKDB_TABLE, current, stale, DUCKDB_CLOSED_TABLE, closed,
    )
    return current


def _rebuild_fts_index(con: duckdb.DuckDBPyConnection) -> None:
    """Rebuild full-text-search index on name/brand/category for quick search."""
    try:
        con.execute(
            f"PRAGMA create_fts_index('{DUCKDB_TABLE}', 'id', 'name', 'brand', "
            "'category', 'address', overwrite = 1);"
        )
        log.info("rebuilt FTS index on %s", DUCKDB_TABLE)
    except duckdb.Error as err:
        log.warning("could not build FTS index (fts extension missing?): %s", err)


def load_to_duckdb(
    parquet_path: Path = CLEAN_PLACES_PARQUET,
    closed_parquet_path: Path = CLOSED_PLACES_PARQUET,
    db_path: Path = DUCKDB_PATH,
) -> int:
    """Apply schema, upsert open + closed places, rebuild FTS index.

    Returns the number of places in the current snapshot.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("loading %s into %s", parquet_path, db_path)
    con = duckdb.connect(str(db_path))
    try:
        _configure(con)
        _apply_schema(con)
        _backfill_first_seen(con)
        new_count = _count_new_ids(con, parquet_path)
        log.info("new businesses since previous run: %d", new_count)
        con.execute("BEGIN TRANSACTION;")
        _upsert_from_parquet(con, parquet_path)
        _move_reopened(con, parquet_path)
        _upsert_closed(con, closed_parquet_path)
        con.execute("COMMIT;")
        _rebuild_fts_index(con)
        return _log_snapshot(con)
    finally:
        con.close()
