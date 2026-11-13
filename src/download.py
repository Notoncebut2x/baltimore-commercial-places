"""Download the Baltimore subset of the Overture Maps places theme.

Uses the official ``overturemaps`` CLI tool (installed as a dependency).
The CLI:

* auto-discovers the latest release (or honours ``OVERTURE_RELEASE``);
* uses the Overture STAC catalog to limit S3 reads to the parquet files
  that intersect the bounding box (so the global dataset is never
  materialised in memory or transferred whole);
* writes a GeoParquet file with the same nested Overture struct columns
  that :mod:`transform` expects.

Each release is kept as its own file, ``data/raw/overture_places_<release>.parquet``.
Overture deletes releases from S3 after ~60 days, so these local copies are
the only way to re-run the pipeline against an older release later.

We shell out instead of binding the library directly because the CLI is the
maintained, supported interface and isolates us from API churn between
``overturemaps-py`` releases.
"""

from __future__ import annotations

import json
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
    RAW_PLACES_DIR,
)

log = logging.getLogger(__name__)

_RAW_PREFIX = "overture_places_"

# click exits with status 2 on a usage error (e.g. a release that no longer
# exists). Retrying those can't succeed, so fail immediately.
_CLI_USAGE_ERROR = 2


def raw_places_path(release: str, raw_dir: Path = RAW_PLACES_DIR) -> Path:
    """Path of the raw parquet for one Overture release."""
    return raw_dir / f"{_RAW_PREFIX}{release}.parquet"


def downloaded_releases(raw_dir: Path = RAW_PLACES_DIR) -> list[str]:
    """Releases with a raw parquet on disk, newest first.

    Release ids are "YYYY-MM-DD.N", so string order is chronological.
    """
    if not raw_dir.exists():
        return []
    return sorted(
        (p.name[len(_RAW_PREFIX):-len(".parquet")]
         for p in raw_dir.glob(f"{_RAW_PREFIX}*.parquet")),
        reverse=True,
    )


def _pinned_release() -> str | None:
    """OVERTURE_RELEASE from the env or config; empty means "latest"."""
    return os.environ.get("OVERTURE_RELEASE", OVERTURE_RELEASE) or None


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


def _release_from_state(output_path: Path) -> str:
    """Read the release the CLI actually downloaded from its ``.state`` file."""
    state_path = Path(f"{output_path}.state")
    try:
        release = json.loads(state_path.read_text())["last_release"]
    except (OSError, ValueError, KeyError) as err:
        raise RuntimeError(
            f"could not read the downloaded release from {state_path}: {err}"
        ) from err
    state_path.unlink()
    return release


def download_places(
    bbox: tuple[float, float, float, float] = BALTIMORE_BBOX,
    release: str | None = None,
    raw_dir: Path = RAW_PLACES_DIR,
) -> tuple[str, Path]:
    """Download Overture places for the bbox; returns (release, parquet_path).

    ``release`` defaults to ``OVERTURE_RELEASE`` (env var or config). If that
    is empty, the latest release is downloaded. A release that is already on
    disk is not downloaded again, since Overture releases never change.
    Earlier releases' files are left in place. Retries on transient errors.
    """
    if shutil.which("overturemaps") is None:
        raise RuntimeError(
            "overturemaps CLI not found on PATH; activate the virtualenv "
            "(`source .venv/bin/activate`) or run `pip install -r requirements.txt`"
        )

    raw_dir.mkdir(parents=True, exist_ok=True)
    release = release or _pinned_release()
    if release is None:
        from overturemaps.releases import get_latest_release
        latest = get_latest_release()
        if raw_places_path(latest, raw_dir).exists():
            log.info("latest release %s is already downloaded", latest)
            return latest, raw_places_path(latest, raw_dir)
        log.info("latest Overture release is %s", latest)
        release = latest
    elif raw_places_path(release, raw_dir).exists():
        log.info("release %s is already downloaded", release)
        return release, raw_places_path(release, raw_dir)

    # Download to a temporary name so a failed or interrupted run never
    # leaves a partial file that looks like a complete release.
    tmp_path = raw_dir / f"{_RAW_PREFIX}download.parquet.partial"
    cmd = _build_command(bbox, tmp_path, release)
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
            if not tmp_path.exists() or tmp_path.stat().st_size == 0:
                raise RuntimeError(
                    f"overturemaps reported success but {tmp_path} is missing/empty"
                )
            # Cross-check against the CLI's own record of what it fetched.
            downloaded = _release_from_state(tmp_path)
            output_path = raw_places_path(downloaded, raw_dir)
            tmp_path.replace(output_path)
            log.info(
                "download complete in %.1fs (%.1f MB), release %s -> %s",
                elapsed, output_path.stat().st_size / (1024 * 1024),
                downloaded, output_path,
            )
            return downloaded, output_path
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError) as err:
            last_err = err
            stderr = getattr(err, "stderr", "") or ""
            if getattr(err, "returncode", None) == _CLI_USAGE_ERROR:
                raise RuntimeError(
                    f"overturemaps rejected the request: {stderr.strip()[:500]}"
                ) from err
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


def count_raw_rows(parquet_path: Path) -> int:
    """Return the row count of a downloaded raw parquet."""
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')"
        ).fetchone()[0]
    finally:
        con.close()
