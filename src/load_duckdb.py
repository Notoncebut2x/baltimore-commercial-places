"""Load the cleaned parquet into DuckDB.

The loader is idempotent: it creates the database and table on first run,
then on subsequent runs performs an upsert keyed on ``id`` so re-ingesting a
fresh Overture release updates changed records and inserts new ones without
losing history.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from config import (
    CLEAN_PLACES_PARQUET,
    DUCKDB_MEMORY_LIMIT,
    DUCKDB_PATH,
    DUCKDB_TABLE,
    DUCKDB_THREADS,
    SQL_DIR,
)

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


def _upsert_from_parquet(con: duckdb.DuckDBPyConnection, parquet_path: Path) -> int:
    """Insert/replace rows from parquet into the target table; returns row count."""
    # DuckDB's INSERT ... ON CONFLICT updates existing keys atomically.
    update_cols = [
        "name", "category", "subtype", "address", "house_number", "street",
        "city", "state", "postcode", "country", "phone", "email", "website",
        "brand", "latitude", "longitude", "geometry_wkt", "source",
        "ingest_timestamp",
    ]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    sql = f"""
        INSERT INTO {DUCKDB_TABLE}
        SELECT * FROM read_parquet('{parquet_path}')
        ON CONFLICT (id) DO UPDATE SET {set_clause};
    """
    con.execute(sql)
    return con.execute(f"SELECT COUNT(*) FROM {DUCKDB_TABLE}").fetchone()[0]


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
    db_path: Path = DUCKDB_PATH,
) -> int:
    """Apply schema, upsert from parquet, rebuild FTS index. Returns row count."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    log.info("loading %s into %s", parquet_path, db_path)
    con = duckdb.connect(str(db_path))
    try:
        _configure(con)
        _apply_schema(con)
        row_count = _upsert_from_parquet(con, parquet_path)
        _rebuild_fts_index(con)
        log.info("duckdb table %s now holds %d rows", DUCKDB_TABLE, row_count)
        return row_count
    finally:
        con.close()
