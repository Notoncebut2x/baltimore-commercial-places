"""Spatial helpers: load the Baltimore City boundary and provide intersection utilities.

The boundary is fetched once from the U.S. Census TIGER/Line Places shapefile
(openly licensed, public-domain) and cached as GeoJSON on disk. Subsequent
runs read from the cache to avoid network calls.
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import geopandas as gpd
import requests
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from config import (
    BALTIMORE_CITY_PLACE_FIPS,
    BOUNDARY_PATH,
    CRS_WGS84,
    DOWNLOAD_MAX_RETRIES,
    DOWNLOAD_RETRY_BACKOFF_SECONDS,
    TIGER_PLACES_URL,
)

log = logging.getLogger(__name__)


def _download_with_retry(url: str) -> bytes:
    """Fetch a URL with simple exponential-ish backoff."""
    import time

    last_err: Exception | None = None
    for attempt in range(1, DOWNLOAD_MAX_RETRIES + 1):
        try:
            log.info("downloading %s (attempt %d/%d)", url, attempt, DOWNLOAD_MAX_RETRIES)
            resp = requests.get(url, timeout=60)
            resp.raise_for_status()
            return resp.content
        except requests.RequestException as err:
            last_err = err
            sleep_for = DOWNLOAD_RETRY_BACKOFF_SECONDS * attempt
            log.warning("download failed (%s); retrying in %.1fs", err, sleep_for)
            time.sleep(sleep_for)
    raise RuntimeError(f"failed to download {url} after {DOWNLOAD_MAX_RETRIES} attempts") from last_err


def _fetch_boundary_from_tiger() -> gpd.GeoDataFrame:
    """Download MD places shapefile from Census TIGER and extract Baltimore City."""
    raw = _download_with_retry(TIGER_PLACES_URL)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        # geopandas can read directly from a zip-protocol URI, but we have bytes,
        # so extract to an in-memory dict and write to a temp dir.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            zf.extractall(tmp)
            shp = next(Path(tmp).glob("*.shp"))
            gdf = gpd.read_file(shp)

    city = gdf[gdf["PLACEFP"] == BALTIMORE_CITY_PLACE_FIPS].copy()
    if city.empty:
        raise RuntimeError(
            f"Baltimore City (PLACEFP={BALTIMORE_CITY_PLACE_FIPS}) not found in TIGER places"
        )
    return city.to_crs(CRS_WGS84)


def load_baltimore_boundary(refresh: bool = False) -> gpd.GeoDataFrame:
    """Return the Baltimore City boundary as a single-row GeoDataFrame in EPSG:4326.

    Caches the result as GeoJSON on first call. Pass ``refresh=True`` to force
    a re-download from Census TIGER.
    """
    if BOUNDARY_PATH.exists() and not refresh:
        log.info("loading cached boundary from %s", BOUNDARY_PATH)
        gdf = gpd.read_file(BOUNDARY_PATH)
        return gdf.to_crs(CRS_WGS84)

    log.info("boundary cache missing or refresh requested; fetching from TIGER")
    BOUNDARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    gdf = _fetch_boundary_from_tiger()
    gdf.to_file(BOUNDARY_PATH, driver="GeoJSON")
    log.info("cached boundary to %s", BOUNDARY_PATH)
    return gdf


def boundary_geometry(gdf: gpd.GeoDataFrame) -> BaseGeometry:
    """Return the unioned single geometry for a boundary GeoDataFrame."""
    if len(gdf) == 1:
        return gdf.geometry.iloc[0]
    return gdf.geometry.union_all()


def from_geojson_dict(geom_dict: dict) -> BaseGeometry:
    """Convert a GeoJSON-style dict to a shapely geometry."""
    return shape(geom_dict)
