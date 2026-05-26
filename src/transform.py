"""Normalize raw Overture places parquet into the analytic schema.

Inputs
------
A parquet file written by :mod:`download` containing raw Overture columns
(many of them nested structs/arrays) for the Baltimore bounding box.

Outputs
-------
A parquet file with a flat schema matching ``commercial_places`` plus a
WKB geometry column. Records outside the precise Baltimore City polygon and
non-commercial categories are dropped before write.
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
    CRS_WGS84,
    EXCLUDED_CATEGORIES,
    EXCLUDED_CATEGORY_PREFIXES,
    RAW_PLACES_PARQUET,
)
from src.spatial_utils import boundary_geometry

log = logging.getLogger(__name__)

SOURCE_NAME: Final[str] = "Overture Maps"

# Final output column order. Matches the DDL in sql/schema.sql.
OUTPUT_COLUMNS: Final[tuple[str, ...]] = (
    "id",
    "name",
    "category",
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
    "ingest_timestamp",
)


# DuckDB SQL that flattens Overture nested structs into scalar columns.
# Overture struct shapes (as of 2024-2025 releases):
#   names           STRUCT(primary VARCHAR, common MAP, rules ...)
#   categories      STRUCT(primary VARCHAR, alternate VARCHAR[])
#   addresses       STRUCT(freeform, locality, postcode, region, country)[]
#   phones / websites / emails  VARCHAR[]
#   brand           STRUCT(names STRUCT(primary VARCHAR, ...), wikidata)
# Each scalar lookup is wrapped in TRY so a schema drift in a future Overture
# release yields NULL rather than a hard failure.
_FLATTEN_SQL = """
SELECT
    id,
    TRY(names.primary)                                              AS name,
    TRY(categories.primary)                                         AS category,
    TRY(categories.alternate[1])                                    AS subtype,
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
    TRY(ST_AsText(geometry))                                        AS geometry_wkt
FROM read_parquet('{raw_parquet}')
WHERE TRY(names.primary) IS NOT NULL
  AND length(TRY(names.primary)) > 0;
"""


def _configure_duckdb(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("INSTALL spatial;")
    con.execute("LOAD spatial;")


def _flatten(raw_parquet: Path) -> pd.DataFrame:
    """Run the DuckDB SQL that explodes nested struct columns into scalars."""
    con = duckdb.connect()
    try:
        _configure_duckdb(con)
        df = con.execute(_FLATTEN_SQL.format(raw_parquet=str(raw_parquet))).df()
    finally:
        con.close()
    log.info("flattened raw places: %d rows", len(df))
    return df


def _apply_category_filter(df: pd.DataFrame) -> pd.DataFrame:
    """Drop rows with no category, or whose category is non-commercial.

    Uses an exclude-list of leaf categories (parks, landmarks, government,
    infrastructure) plus a prefix list for whole excluded families. All
    other named POIs are retained as "commercial or customer-facing".
    """
    if df.empty:
        return df

    cat = df["category"].fillna("")
    has_category = cat.str.len() > 0
    excluded_leaf = cat.isin(EXCLUDED_CATEGORIES)
    excluded_prefix = pd.Series(False, index=df.index)
    for pfx in EXCLUDED_CATEGORY_PREFIXES:
        excluded_prefix |= cat.str.startswith(pfx)

    filtered = df[has_category & ~excluded_leaf & ~excluded_prefix].copy()
    log.info(
        "category filter kept %d / %d rows (%.1f%%)",
        len(filtered),
        len(df),
        100.0 * len(filtered) / max(len(df), 1),
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


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Add static columns, enforce column order, and de-duplicate by id."""
    if df.empty:
        for col in OUTPUT_COLUMNS:
            if col not in df.columns:
                df[col] = pd.Series(dtype="object")
        return df[list(OUTPUT_COLUMNS)]

    df["source"] = SOURCE_NAME
    df["ingest_timestamp"] = datetime.now(timezone.utc)

    before = len(df)
    df = df.drop_duplicates(subset=["id"], keep="first")
    if len(df) != before:
        log.info("dropped %d duplicate ids", before - len(df))

    # Ensure UTF-8 safety on string columns.
    string_cols = [
        c for c in OUTPUT_COLUMNS if c not in {"latitude", "longitude", "ingest_timestamp"}
    ]
    for col in string_cols:
        if col in df.columns:
            df[col] = df[col].astype("string").str.encode("utf-8", "ignore").str.decode("utf-8")

    return df[list(OUTPUT_COLUMNS)]


def transform_places(
    boundary: gpd.GeoDataFrame,
    raw_parquet: Path = RAW_PLACES_PARQUET,
    output_path: Path = CLEAN_PLACES_PARQUET,
) -> Path:
    """End-to-end transform: flatten -> category filter -> polygon filter -> write parquet.

    Returns the path to the cleaned parquet file.
    """
    df = _flatten(raw_parquet)
    df = _apply_category_filter(df)
    df = _apply_polygon_filter(df, boundary)
    df = _finalize(df)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False, compression="zstd")
    log.info("wrote %d clean rows to %s", len(df), output_path)
    return output_path
