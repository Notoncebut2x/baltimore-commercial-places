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
RAW_PLACES_PARQUET: Final[Path] = DATA_DIR / "overture_places_raw.parquet"
CLEAN_PLACES_PARQUET: Final[Path] = DATA_DIR / "commercial_places.parquet"

DUCKDB_PATH: Final[Path] = PROJECT_ROOT / "baltimore_commercial_places.duckdb"
DUCKDB_TABLE: Final[str] = "commercial_places"

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
# Overture's `categories.primary` field is the LEAF in the category taxonomy
# (e.g. "restaurant", "grocery_store", "barber") rather than a dotted path.
# With ~2000+ leaf values, an allow-list is fragile; instead we use an
# exclude-list of leaves that are clearly non-commercial (parks, landmarks,
# government, infrastructure) plus prefix patterns for whole excluded
# families. Rows missing a name or category are dropped upstream.
# See https://github.com/OvertureMaps/schema/blob/main/task-force-docs/places/overture_categories.csv

EXCLUDED_CATEGORIES: Final[frozenset[str]] = frozenset({
    # parks / open space / natural features
    "park", "national_park", "state_park", "dog_park", "playground",
    "public_plaza", "cemetery", "forest", "beach", "lake", "river",
    "mountain", "garden", "botanical_garden",
    # landmarks / monuments
    "landmark_and_historical_building", "monument", "statue", "historic_site",
    # transport infrastructure
    "parking", "parking_lot", "parking_garage", "rest_area",
    "bridge", "tunnel", "intersection", "bus_stop", "train_station",
    "subway_station", "transit_station",
    # government / civic
    "government_office", "city_hall", "town_hall", "courthouse",
    "post_office", "police_station", "fire_station",
    "public_and_government_association",
})

# Any leaf whose name starts with one of these prefixes is also dropped.
# Catches families like "government_*", "public_*_infrastructure", etc.
EXCLUDED_CATEGORY_PREFIXES: Final[tuple[str, ...]] = (
    "government_",
    "public_transportation",
    "civic_",
    "military_",
)

# ---------------------------------------------------------------------------
# Runtime tuning
# ---------------------------------------------------------------------------
DOWNLOAD_MAX_RETRIES: Final[int] = 3
DOWNLOAD_RETRY_BACKOFF_SECONDS: Final[float] = 5.0

# DuckDB memory limit. Overture places nationwide is large, but our predicate
# pushdown keeps the working set small; this is a safety cap.
DUCKDB_MEMORY_LIMIT: Final[str] = os.environ.get("DUCKDB_MEMORY_LIMIT", "4GB")
DUCKDB_THREADS: Final[int] = int(os.environ.get("DUCKDB_THREADS", "4"))
