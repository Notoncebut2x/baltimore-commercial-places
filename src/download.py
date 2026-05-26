"""Download the Baltimore subset of the Overture Maps places theme.

Uses the official ``overturemaps`` CLI tool (installed as a dependency).
The CLI:

* auto-discovers the latest release (or honours ``OVERTURE_RELEASE``);
* uses the Overture STAC catalog to limit S3 reads to the parquet files
  that intersect the bounding box (so the global dataset is never
  materialised in memory or transferred whole);
* writes a GeoParquet file with the same nested Overture struct columns
  that :mod:`transform` expects.

We shell out instead of binding the library directly because the CLI is the
maintained, supported interface and isolates us from API churn between
``overturemaps-py`` releases.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

import duckdb

from config import (
    BALTIMORE_BBOX,
    DOWNLOAD_MAX_RETRIES,
    DOWNLOAD_RETRY_BACKOFF_SECONDS,
    OVERTURE_RELEASE,
    RAW_PLACES_PARQUET,
)

log = logging.getLogger(__name__)


def _build_command(
    bbox: tuple[float, float, float, float],
    output_path: Path,
    release: str | None,
) -> list[str]:
    xmin, ymin, xmax, ymax = bbox
    cmd = [
        "overturemaps", "download",
        "--bbox", f"{xmin},{ymin},{xmax},{ymax}",
        "-t", "place",
        "-f", "geoparquet",
        "-o", str(output_path),
    ]
    if release:
        cmd.extend(["-r", release])
    return cmd


def download_places(
    output_path: Path = RAW_PLACES_PARQUET,
    bbox: tuple[float, float, float, float] = BALTIMORE_BBOX,
    release: str | None = None,
) -> Path:
    """Download Overture places for the given bbox into a local GeoParquet file.

    ``release`` defaults to the ``OVERTURE_RELEASE`` env var (set via config).
    If the env var is unset or the empty string, the CLI's built-in "latest"
    is used - safer than pinning a release that may not exist yet.

    Returns the path to the written parquet file. Retries on transient errors.
    """
    if shutil.which("overturemaps") is None:
        raise RuntimeError(
            "overturemaps CLI not found on PATH; run `pip install -r requirements.txt`"
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if release is None:
        # Allow OVERTURE_RELEASE='' to mean "latest".
        env_release = os.environ.get("OVERTURE_RELEASE", OVERTURE_RELEASE)
        release = env_release or None

    cmd = _build_command(bbox, output_path, release)
    log.info("running: %s", " ".join(cmd))

    last_err: Exception | None = None
    for attempt in range(1, DOWNLOAD_MAX_RETRIES + 1):
        t0 = time.perf_counter()
        try:
            result = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
            )
            elapsed = time.perf_counter() - t0
            if result.stdout.strip():
                log.debug("overturemaps stdout: %s", result.stdout.strip())
            if result.stderr.strip():
                log.debug("overturemaps stderr: %s", result.stderr.strip())
            if not output_path.exists() or output_path.stat().st_size == 0:
                raise RuntimeError(
                    f"overturemaps reported success but {output_path} is missing/empty"
                )
            log.info(
                "download complete in %.1fs (%.1f MB)",
                elapsed, output_path.stat().st_size / (1024 * 1024),
            )
            return output_path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError) as err:
            last_err = err
            stderr = getattr(err, "stderr", "") or ""
            sleep_for = DOWNLOAD_RETRY_BACKOFF_SECONDS * attempt
            log.warning(
                "overture download attempt %d/%d failed: %s%s; retrying in %.1fs",
                attempt, DOWNLOAD_MAX_RETRIES, err,
                f" | stderr: {stderr.strip()[:500]}" if stderr else "",
                sleep_for,
            )
            time.sleep(sleep_for)

    raise RuntimeError(
        f"failed to download Overture places after {DOWNLOAD_MAX_RETRIES} attempts"
    ) from last_err


def count_raw_rows(parquet_path: Path = RAW_PLACES_PARQUET) -> int:
    """Return the row count of the downloaded raw parquet."""
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')"
        ).fetchone()[0]
    finally:
        con.close()
