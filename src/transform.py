"""Normalize raw Overture places parquet into the analytic schema.

Inputs
------
A parquet file written by :mod:`download` containing raw Overture columns
(many of them nested structs/arrays) for the Baltimore bounding box.

Outputs
-------
Two parquet files with a flat schema matching ``commercial_places``:
open places, and permanently closed places (destined for ``closed_places``).
Records outside the precise Baltimore City polygon and non-commercial
taxonomy branches are dropped from both before write.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import duckdb
import geopandas as gpd
import pandas as pd

from config import (
    CLEAN_PLACES_PARQUET,
    CLOSED_PLACES_PARQUET,
    CRS_WGS84,
    EXCLUDED_TAXONOMY_PATHS,
    MIN_CONFIDENCE,
)
from src.spatial_utils import boundary_geometry

log = logging.getLogger(__name__)

SOURCE_NAME: Final[str] = "Overture Maps"

# Final output column order. Matches the DDL in sql/schema.sql.
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "name",
    "category",
    "category_l1",
    "category_l2",
    "category_l3",
    "subtype",
    "address",
    "house_number",
    "street",
    "city",
    "state",
    "postcode",
    "country",
    "phone",
    "email",
    "website",
    "brand",
    "latitude",
    "longitude",
    "geometry_wkt",
    "source",
    "source_dataset",
    "confidence",
    "ingest_timestamp",
    "first_seen_at",
    "basic_category",
    "last_seen_at",
    "last_seen_release",
)

CLOSED_STATUS: Final[str] = "permanently_closed"

# DuckDB SQL that flattens Overture nested structs into scalar columns.
# Overture struct shapes (as of the 2026 releases):
#   names           STRUCT(primary VARCHAR, common MAP, rules ...)
#   taxonomy        STRUCT(primary VARCHAR, hierarchy VARCHAR[], alternates VARCHAR[])
#   addresses       STRUCT(freeform, locality, postcode, region, country)[]
#   phones / websites / emails  VARCHAR[]
#   brand           STRUCT(names STRUCT(primary VARCHAR, ...), wikidata)
# Each scalar lookup is wrapped in TRY so a schema drift in a future Overture
# release yields NULL rather than a hard failure.
_FLATTEN_SQL = """
SELECT
    id,
    TRY(names.primary)                                              AS name,
    TRY(taxonomy.primary)                                           AS category,
    -- Top three levels of the taxonomy path, e.g. food_and_drink >
    -- restaurant > asian_restaurant. NULL where the path is shallower.
    TRY(taxonomy.hierarchy[1])                                      AS category_l1,
    TRY(taxonomy.hierarchy[2])                                      AS category_l2,
    TRY(taxonomy.hierarchy[3])                                      AS category_l3,
    -- Full path, used for the taxonomy exclude filter; not written out.
    TRY(array_to_string(taxonomy.hierarchy, '/'))                   AS category_path,
    -- Overture's own coarse grouping (e.g. "automotive_service").
    TRY(basic_category)                                             AS basic_category,
    TRY(operating_status)                                           AS operating_status,
    TRY(taxonomy.alternates[1])                                     AS subtype,
    TRY(addresses[1].freeform)                                      AS address,
    TRY(regexp_extract(addresses[1].freeform, '^([0-9A-Za-z-]+)\\s', 1))
                                                                    AS house_number,
    TRY(trim(regexp_replace(addresses[1].freeform, '^[0-9A-Za-z-]+\\s', '')))
                                                                    AS street,
    TRY(addresses[1].locality)                                      AS city,
    TRY(addresses[1].region)                                        AS state,
    TRY(addresses[1].postcode)                                      AS postcode,
    TRY(addresses[1].country)                                       AS country,
    TRY(phones[1])                                                  AS phone,
    TRY(emails[1])                                                  AS email,
    TRY(websites[1])                                                AS website,
    TRY(brand.names.primary)                                        AS brand,
    TRY(ST_Y(geometry))                                             AS latitude,
    TRY(ST_X(geometry))                                             AS longitude,
    TRY(ST_AsText(geometry))                                        AS geometry_wkt,
    -- Primary contributing dataset (e.g. meta, Microsoft, Foursquare).
    -- The Overture `sources` array carries one entry per property; the entry
    -- whose `property` is the empty string applies to the whole record.
    TRY(list_filter(sources, x -> x.property = '')[1].dataset)      AS source_dataset,
    confidence
FROM read_parquet('{raw_parquet}')
WHERE TRY(names.primary) IS NOT NULL
  AND length(TRY(names.primary)) > 0
  -- Closed places skip the confidence floor: they are kept as history, and
  -- confidence measures whether a place exists, which no longer applies.
  AND (confidence >= {min_confidence} OR operating_status = 'permanently_closed');
"""


def _configure_duckdb(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("INSTALL spatial;")
    con.execute("LOAD spatial;")


def _flatten(raw_parquet: Path) -> pd.DataFrame:
    """Run the DuckDB SQL that explodes nested struct columns into scalars."""
    con = duckdb.connect()
    try:
        _configure_duckdb(con)
        df = con.execute(_FLATTEN_SQL.format(
            raw_parquet=str(raw_parquet), min_confidence=MIN_CONFIDENCE,
        )).df()
    finally:
        con.close()
    log.info(
        "flattened raw places: %d rows (confidence >= %.2f)",
        len(df), MIN_CONFIDENCE,
    )
    return df


def _apply_category_filter(
    df: pd.DataFrame,
    excluded_paths: tuple[str, ...] = EXCLUDED_TAXONOMY_PATHS,
) -> pd.DataFrame:
    """Drop places with no taxonomy or in an excluded taxonomy branch.

    A path such as "sports_and_recreation/park" excludes that node and every
    descendant. Matching on "path/" with a trailing slash keeps
    "food_and_drink/bar" from also excluding "food_and_drink/bar_and_grill".
    """
    if df.empty:
        return df

    path = df["category_path"].fillna("")
    has_taxonomy = path.str.len() > 0
    padded = path + "/"
    excluded = pd.Series(False, index=df.index)
    for prefix in excluded_paths:
        excluded |= padded.str.startswith(prefix.rstrip("/") + "/")

    filtered = df[has_taxonomy & ~excluded].copy()
    log.info(
        "taxonomy filter kept %d / %d rows (%.1f%%): %d had no taxonomy, "
        "%d in excluded branches",
        len(filtered),
        len(df),
        100.0 * len(filtered) / max(len(df), 1),
        int((~has_taxonomy).sum()),
        int((has_taxonomy & excluded).sum()),
    )
    return filtered


def _apply_polygon_filter(df: pd.DataFrame, boundary: gpd.GeoDataFrame) -> pd.DataFrame:
    """Drop rows whose point geometry falls outside the Baltimore polygon."""
    if df.empty:
        return df

    gdf = gpd.GeoDataFrame(
        df,
        geometry=gpd.points_from_xy(df["longitude"], df["latitude"], crs=CRS_WGS84),
    )
    boundary_geom = boundary_geometry(boundary)
    inside = gdf[gdf.geometry.within(boundary_geom)].copy()
    log.info(
        "polygon filter kept %d / %d rows (%.1f%%)",
        len(inside),
        len(df),
        100.0 * len(inside) / max(len(df), 1),
    )
    return pd.DataFrame(inside.drop(columns="geometry"))


def _finalize(df: pd.DataFrame, now: datetime, release: str | None) -> pd.DataFrame:
    """Add static columns, enforce column order, and de-duplicate by id."""
    if df.empty:
        for col in OUTPUT_COLUMNS:
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        return df[list(OUTPUT_COLUMNS)]

    df["source"] = SOURCE_NAME
    df["ingest_timestamp"] = now
    # Provisional first_seen_at; the DuckDB upsert preserves the existing
    # value on conflict, so this only "wins" for IDs not yet in the table.
    df["first_seen_at"] = now
    # Every row in this run shares last_seen_at, so the exporter can select
    # the current snapshot with last_seen_at = MAX(last_seen_at).
    df["last_seen_at"] = now
    df["last_seen_release"] = release

    before = len(df)
    df = df.drop_duplicates(subset=["id"], keep="first")
    if len(df) != before:
        log.info("dropped %d duplicate ids", before - len(df))

    # Ensure UTF-8 safety on string columns.
    string_cols = [
        c for c in OUTPUT_COLUMNS
        if c not in {
            "latitude", "longitude", "confidence",
            "ingest_timestamp", "first_seen_at", "last_seen_at",
        }
    ]
    for col in string_cols:
        if col in df.columns:
            df[col] = df[col].astype("string").str.encode("utf-8", "ignore").str.decode("utf-8")

    return df[list(OUTPUT_COLUMNS)]


def transform_places(
    boundary: gpd.GeoDataFrame,
    release: str,
    raw_parquet: Path,
    output_path: Path = CLEAN_PLACES_PARQUET,
    closed_output_path: Path = CLOSED_PLACES_PARQUET,
) -> tuple[Path, Path]:
    """End-to-end transform: flatten -> category filter -> polygon filter -> write parquet.

    Permanently closed places are split off into ``closed_output_path``.
    ``release`` is the Overture release the raw parquet came from.
    Returns (open_path, closed_path).
    """
    df = _flatten(raw_parquet)
    df = _apply_category_filter(df)
    df = _apply_polygon_filter(df, boundary)

    is_closed = df["operating_status"] == CLOSED_STATUS
    now = datetime.now(timezone.utc)
    open_df = _finalize(df[~is_closed].copy(), now, release)
    closed_df = _finalize(df[is_closed].copy(), now, release)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    open_df.to_parquet(output_path, index=False, compression="zstd")
    closed_df.to_parquet(closed_output_path, index=False, compression="zstd")
    log.info("wrote %d open rows to %s", len(open_df), output_path)
    log.info("wrote %d permanently closed rows to %s", len(closed_df), closed_output_path)
    return output_path, closed_output_path
