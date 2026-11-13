"""Export commercial_places from DuckDB to web/places.geojson for the map UI.

The exporter only includes columns the front-end needs, which keeps the file
size down (~5 MB for 25k Baltimore places). Run via:

    python src/export_geojson.py                       # MIN_CONFIDENCE from config.py
    python src/export_geojson.py --min-confidence 0.8  # custom threshold
    python src/export_geojson.py --min-confidence 0    # no confidence filter
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import DUCKDB_PATH, DUCKDB_TABLE, MIN_CONFIDENCE

log = logging.getLogger(__name__)

OUTPUT_PATH: Path = PROJECT_ROOT / "web" / "places.geojson"

# is_new flags rows that share the latest first_seen_at — i.e. the IDs that
# only appeared in the most recent ETL run. Guarded by a "more than one
# distinct first_seen_at exists" check so a fresh DB (where every row shares
# one ingest timestamp) doesn't paint everything red.
# Only the current snapshot (rows seen in the latest pipeline run) is
# exported; stale rows stay in DuckDB for history. Permanently closed places
# live in a separate table and are never exported.
# A threshold of 0 disables the confidence filter.
_EXPORT_SQL = f"""
SELECT
    id, name, category, category_l1, category_l2, category_l3, basic_category, subtype, address, postcode,
    phone, email, website, brand, source_dataset, confidence, latitude, longitude,
    CAST(first_seen_at AS VARCHAR) AS first_seen_at,
    (
        first_seen_at = (SELECT MAX(first_seen_at) FROM {DUCKDB_TABLE})
        AND (SELECT COUNT(DISTINCT first_seen_at) FROM {DUCKDB_TABLE}) > 1
    ) AS is_new
FROM {DUCKDB_TABLE}
WHERE latitude IS NOT NULL AND longitude IS NOT NULL
  AND last_seen_at = (SELECT MAX(last_seen_at) FROM {DUCKDB_TABLE})
  AND (? <= 0 OR confidence >= ?);
"""


def export(
    db_path: Path = DUCKDB_PATH,
    output_path: Path = OUTPUT_PATH,
    min_confidence: float = MIN_CONFIDENCE,
) -> int:
    """Write a GeoJSON FeatureCollection of places at or above min_confidence.

    Returns feature count.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(_EXPORT_SQL, [min_confidence, min_confidence]).fetchall()
        cols = [d[0] for d in con.description]
    finally:
        con.close()

    features = []
    for row in rows:
        rec = dict(zip(cols, row))
        lon, lat = rec.pop("longitude"), rec.pop("latitude")
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": rec,
        })

    fc = {"type": "FeatureCollection", "features": features}
    output_path.write_text(json.dumps(fc, separators=(",", ":"), default=str))
    log.info("wrote %d features to %s (%.1f MB, confidence >= %.2f)",
             len(features), output_path, output_path.stat().st_size / 1_000_000,
             min_confidence)
    return len(features)


def _confidence(value: str) -> float:
    f = float(value)
    if not 0.0 <= f <= 1.0:
        raise argparse.ArgumentTypeError(f"must be between 0 and 1, got {value}")
    return f


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--min-confidence", type=_confidence, default=MIN_CONFIDENCE,
        help=f"drop places below this Overture confidence score, 0-1 "
             f"(default: {MIN_CONFIDENCE}; 0 disables the filter)",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    export(min_confidence=args.min_confidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
