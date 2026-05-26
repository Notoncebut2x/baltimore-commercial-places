"""Orchestrate the Baltimore commercial-places ETL pipeline.

Run from the project root:

    python src/main.py
    python src/main.py --refresh-boundary
    python src/main.py --skip-download   # reuse existing data/overture_places_raw.parquet
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow running as `python src/main.py` from the project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import (
    CLEAN_PLACES_PARQUET,
    DUCKDB_PATH,
    LOG_DIR,
    RAW_PLACES_PARQUET,
)
from src.download import count_raw_rows, download_places
from src.load_duckdb import load_to_duckdb
from src.spatial_utils import load_baltimore_boundary
from src.transform import transform_places

log = logging.getLogger("baltimore_etl")


def _setup_logging(verbose: bool) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "pipeline.log"
    level = logging.DEBUG if verbose else logging.INFO
    fmt = "%(asctime)s %(levelname)s %(name)s %(message)s"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file, encoding="utf-8"),
    ]
    logging.basicConfig(level=level, format=fmt, handlers=handlers, force=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Baltimore commercial places ETL (Overture Maps -> DuckDB)",
    )
    parser.add_argument(
        "--refresh-boundary",
        action="store_true",
        help="Force re-download of the Baltimore City boundary from Census TIGER",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Reuse an existing raw Overture parquet (data/overture_places_raw.parquet)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose (DEBUG) logging",
    )
    return parser.parse_args(argv)


def run(refresh_boundary: bool = False, skip_download: bool = False) -> int:
    """Execute the full pipeline. Returns the final DuckDB row count."""
    t_start = time.perf_counter()

    log.info("step 1/5 - loading Baltimore boundary")
    boundary = load_baltimore_boundary(refresh=refresh_boundary)
    log.info("boundary area (deg^2): %.4f", boundary.geometry.area.iloc[0])

    log.info("step 2/5 - downloading Overture places (predicate-pushdown bbox)")
    if skip_download and RAW_PLACES_PARQUET.exists():
        log.info("--skip-download set; reusing %s", RAW_PLACES_PARQUET)
    else:
        download_places()

    raw_count = count_raw_rows()
    log.info("raw bbox row count: %d", raw_count)

    log.info("step 3/5 - normalizing schema")
    log.info("step 4/5 - precise polygon intersection + category filter")
    transform_places(boundary=boundary)

    log.info("step 5/5 - loading into DuckDB")
    final_count = load_to_duckdb()

    elapsed = time.perf_counter() - t_start
    log.info(
        "pipeline complete: raw=%d clean_parquet=%s db=%s rows=%d runtime=%.1fs",
        raw_count, CLEAN_PLACES_PARQUET, DUCKDB_PATH, final_count, elapsed,
    )
    return final_count


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    _setup_logging(verbose=args.verbose)
    try:
        run(refresh_boundary=args.refresh_boundary, skip_download=args.skip_download)
        return 0
    except Exception:
        log.exception("pipeline failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
