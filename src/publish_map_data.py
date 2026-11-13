"""Publish web/places.geojson for the GitHub Pages map and trigger a deploy.

The GeoJSON is too large to commit on every refresh, so it lives as an asset
on a GitHub Release (tag ``map-data``) instead of in the git history. The
Pages workflow downloads it from there at deploy time. Run after exporting:

    python src/export_geojson.py
    python src/publish_map_data.py              # upload + redeploy the site
    python src/publish_map_data.py --no-deploy  # upload only

Requires the GitHub CLI (``gh``), logged in with push access to the repo.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.export_geojson import OUTPUT_PATH

log = logging.getLogger(__name__)

RELEASE_TAG = "map-data"
DEPLOY_WORKFLOW = "deploy-pages.yml"
DEPLOY_BRANCH = "main"


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["gh", *args], cwd=PROJECT_ROOT, check=check, capture_output=True, text=True,
    )


def _ensure_release() -> None:
    """Create the map-data release on first use."""
    if _gh("release", "view", RELEASE_TAG, check=False).returncode == 0:
        return
    log.info("creating release %s", RELEASE_TAG)
    _gh(
        "release", "create", RELEASE_TAG,
        "--title", "Map data",
        "--notes", "places.geojson for the GitHub Pages map. Replaced by "
                   "src/publish_map_data.py on each refresh; not a code release.",
        "--latest=false",
    )


def publish(geojson_path: Path = OUTPUT_PATH, deploy: bool = True) -> None:
    """Upload the GeoJSON to the map-data release, then optionally redeploy."""
    if shutil.which("gh") is None:
        raise RuntimeError("GitHub CLI `gh` not found; install it with `brew install gh`")
    if not geojson_path.exists():
        raise RuntimeError(
            f"{geojson_path} not found; run `python src/export_geojson.py` first"
        )

    _ensure_release()
    log.info(
        "uploading %s (%.1f MB) to release %s",
        geojson_path, geojson_path.stat().st_size / 1_000_000, RELEASE_TAG,
    )
    _gh("release", "upload", RELEASE_TAG, str(geojson_path), "--clobber")

    if deploy:
        _gh("workflow", "run", DEPLOY_WORKFLOW, "--ref", DEPLOY_BRANCH)
        log.info(
            "triggered %s on %s; follow it with `gh run watch`",
            DEPLOY_WORKFLOW, DEPLOY_BRANCH,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--no-deploy", action="store_true",
        help="upload the file but don't trigger the Pages deploy",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        publish(deploy=not args.no_deploy)
    except subprocess.CalledProcessError as err:
        log.error("gh %s failed: %s", " ".join(err.cmd[1:3]), (err.stderr or "").strip())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
