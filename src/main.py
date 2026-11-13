"""Orchestrate the Baltimore commercial-places ETL pipeline.

Run from the project root:

    python src/main.py
    python src/main.py --refresh-boundary
    python src/main.py --skip-download   # reuse the newest release in data/raw/
    python src/main.py --release 2026-09-23.0   # process a specific release
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
    RAW_PLACES_DIR,
)
from src.download import (
    count_raw_rows,
    download_places,
    downloaded_releases,
    raw_places_path,
)
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
        help="Don't check for a new release; reuse the newest one in data/raw/",
    )
    parser.add_argument(
        "--release",
        help="Process this Overture release (e.g. 2026-09-23.0). Uses the copy "
             "in data/raw/ if present, otherwise downloads it (Overture only "
             "hosts the last ~60 days of releases)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose (DEBUG) logging",
    )
    return parser.parse_args(argv)


def _select_release(skip_download: bool, release: str | None) -> tuple[str, Path]:
    """Pick the raw parquet to process: download, or reuse a local release."""
    if release and raw_places_path(release).exists():
        log.info("using local copy of release %s", release)
        return release, raw_places_path(release)
    if skip_download and not release:
        local = downloaded_releases()
        if not local:
            raise RuntimeError(
                f"--skip-download set but no releases found in {RAW_PLACES_DIR}"
            )
        log.info("--skip-download set; reusing newest local release %s", local[0])
        return local[0], raw_places_path(local[0])
    return download_places(release=release)


def run(
    refresh_boundary: bool = False,
    skip_download: bool = False,
    release: str | None = None,
) -> int:
    """Execute the full pipeline. Returns the current-snapshot row count."""
    t_start = time.perf_counter()

    log.info("step 1/5 - loading Baltimore boundary")
    boundary = load_baltimore_boundary(refresh=refresh_boundary)
    log.info("boundary area (deg^2): %.4f", boundary.geometry.area.iloc[0])

    log.info("step 2/5 - downloading Overture places (predicate-pushdown bbox)")
    release, raw_parquet = _select_release(skip_download, release)
    raw_count = count_raw_rows(raw_parquet)
    log.info("raw bbox row count: %d, Overture release: %s", raw_count, release)
    others = [r for r in downloaded_releases() if r != release]
    if others:
        log.info("other releases kept in %s: %s", RAW_PLACES_DIR, ", ".join(others))

    log.info("step 3/5 - normalizing schema")
    log.info("step 4/5 - precise polygon intersection + category filter")
    transform_places(boundary=boundary, release=release, raw_parquet=raw_parquet)

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
        run(
            refresh_boundary=args.refresh_boundary,
            skip_download=args.skip_download,
            release=args.release,
        )
        return 0
    except Exception:
        log.exception("pipeline failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
