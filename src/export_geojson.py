"""Export commercial_places from DuckDB to web/places.geojson for the map UI.

The exporter only includes columns the front-end needs, which keeps the file
size down (~5 MB for 25k Baltimore places). Run via:

    python src/export_geojson.py
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import duckdb

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import DUCKDB_PATH, DUCKDB_TABLE

log = logging.getLogger(__name__)

OUTPUT_PATH: Path = PROJECT_ROOT / "web" / "places.geojson"

_EXPORT_SQL = f"""
SELECT
    id, name, category, subtype, address, postcode,
    phone, email, website, brand, latitude, longitude
FROM {DUCKDB_TABLE}
WHERE latitude IS NOT NULL AND longitude IS NOT NULL;
"""


def export(db_path: Path = DUCKDB_PATH, output_path: Path = OUTPUT_PATH) -> int:
    """Write a GeoJSON FeatureCollection of all places. Returns feature count."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(_EXPORT_SQL).fetchall()
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
    log.info("wrote %d features to %s (%.1f MB)",
             len(features), output_path, output_path.stat().st_size / 1_000_000)
    return len(features)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    export()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
