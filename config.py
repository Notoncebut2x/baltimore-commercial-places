"""Central configuration for the Baltimore commercial-places ETL pipeline.

All paths are computed relative to this file so the project is location-independent.
Tunable parameters (Overture release, bounding box, category filters) live here so
the pipeline can be re-pointed at a new Overture release with a one-line change.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent
DATA_DIR: Final[Path] = PROJECT_ROOT / "data"
SQL_DIR: Final[Path] = PROJECT_ROOT / "sql"
LOG_DIR: Final[Path] = PROJECT_ROOT / "logs"

BOUNDARY_PATH: Final[Path] = DATA_DIR / "baltimore_boundary.geojson"
# One raw parquet per Overture release: overture_places_<release>.parquet.
# Old releases are kept because Overture deletes them from S3 after ~60 days.
RAW_PLACES_DIR: Final[Path] = DATA_DIR / "raw"
CLEAN_PLACES_PARQUET: Final[Path] = DATA_DIR / "commercial_places.parquet"
CLOSED_PLACES_PARQUET: Final[Path] = DATA_DIR / "closed_places.parquet"

DUCKDB_PATH: Final[Path] = PROJECT_ROOT / "baltimore_commercial_places.duckdb"
DUCKDB_TABLE: Final[str] = "commercial_places"
# Permanently closed places. Kept for history, never exported to the map.
DUCKDB_CLOSED_TABLE: Final[str] = "closed_places"

# ---------------------------------------------------------------------------
# Overture release
# ---------------------------------------------------------------------------
# Overture publishes monthly. Empty string means "use the CLI's latest
# release", which is safer than pinning a date that may not exist yet.
# Override via env var when you need to reproduce a specific release.
# Releases are listed at https://docs.overturemaps.org/release/latest/
OVERTURE_RELEASE: Final[str] = os.environ.get("OVERTURE_RELEASE", "")

# ---------------------------------------------------------------------------
# Geographic scope - Baltimore City, MD
# ---------------------------------------------------------------------------
# Bounding box (xmin, ymin, xmax, ymax) in EPSG:4326. Used as a coarse
# predicate-pushdown filter before the precise polygon intersection.
BALTIMORE_BBOX: Final[tuple[float, float, float, float]] = (
    -76.7113,  # west
    39.1972,   # south
    -76.5294,  # east
    39.3722,   # north
)

# Baltimore City FIPS place code (used for Census TIGER boundary lookup).
MD_STATE_FIPS: Final[str] = "24"
BALTIMORE_CITY_PLACE_FIPS: Final[str] = "04000"

# Census TIGER 2024 places shapefile - small (~1 MB) and openly licensed.
TIGER_PLACES_URL: Final[str] = (
    "https://www2.census.gov/geo/tiger/TIGER2024/PLACE/tl_2024_24_place.zip"
)

CRS_WGS84: Final[str] = "EPSG:4326"

# ---------------------------------------------------------------------------
# Commercial category filter
# ---------------------------------------------------------------------------
# Places are matched on Overture's `taxonomy.hierarchy` path, written as
# "level1/level2/level3". Each entry drops that node and everything beneath
# it, e.g. "sports_and_recreation/park" drops parks, dog parks, playgrounds...
# Everything not listed is kept as commercial / customer-facing. Places with
# no taxonomy at all are dropped.
# Taxonomy reference: https://docs.overturemaps.org/guides/places/
EXCLUDED_TAXONOMY_PATHS: Final[tuple[str, ...]] = (
    "community_and_government/government_office",
    "community_and_government/public_safety_service",
    "community_and_government/public_facility",
    "community_and_government/military_site",
    "cultural_and_historic/historic_site",
    "cultural_and_historic/memorial_site",
    "geographic_entities",
    "sports_and_recreation/park",
    "sports_and_recreation/recreational_trail_or_path",
    "travel_and_transportation/parking",
    "travel_and_transportation/ground_transport_facility_or_service/rail_facility_or_service",
    "services_and_business/shipping_or_delivery_service/post_office",
)

# ---------------------------------------------------------------------------
# Confidence filter
# ---------------------------------------------------------------------------
# Overture's `confidence` (0-1) estimates how likely a place is to exist.
# Rows below this threshold are dropped in the transform step, so it can be
# re-tuned with `--skip-download` without re-fetching the raw parquet.
MIN_CONFIDENCE: Final[float] = float(os.environ.get("MIN_CONFIDENCE", "0.5"))

# ---------------------------------------------------------------------------
# Runtime tuning
# ---------------------------------------------------------------------------
DOWNLOAD_MAX_RETRIES: Final[int] = 3
DOWNLOAD_RETRY_BACKOFF_SECONDS: Final[float] = 5.0

# DuckDB memory limit. Overture places nationwide is large, but our predicate
# pushdown keeps the working set small; this is a safety cap.
DUCKDB_MEMORY_LIMIT: Final[str] = os.environ.get("DUCKDB_MEMORY_LIMIT", "4GB")
DUCKDB_THREADS: Final[int] = int(os.environ.get("DUCKDB_THREADS", "4"))
