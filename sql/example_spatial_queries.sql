-- Spatial example queries. Require the DuckDB spatial extension.
-- Run via: duckdb baltimore_commercial_places.duckdb < sql/example_spatial_queries.sql

INSTALL spatial;
LOAD spatial;

-- 1. All places within 500 meters of a point in downtown Baltimore.
--    ST_DWithin uses planar distance in the input CRS. Wrap with a geographic
--    projection (EPSG:3857) for meter units.
WITH origin AS (
    SELECT ST_Transform(ST_Point(-76.6122, 39.2904), 'EPSG:4326', 'EPSG:3857') AS g
)
SELECT cp.name, cp.category, cp.address
FROM commercial_places cp, origin
WHERE ST_DWithin(
    ST_Transform(ST_Point(cp.longitude, cp.latitude), 'EPSG:4326', 'EPSG:3857'),
    origin.g,
    500
)
ORDER BY cp.name;

-- 2. Restaurants in Federal Hill (approximate bounding box)
SELECT name, address
FROM commercial_places
WHERE category LIKE 'eat_and_drink%'
  AND longitude BETWEEN -76.615 AND -76.598
  AND latitude  BETWEEN 39.270  AND 39.281;

-- 3. Density grid: places per 0.005-degree quad (~500 m near Baltimore latitude)
SELECT
    ROUND(longitude / 0.005) * 0.005 AS lon_bin,
    ROUND(latitude  / 0.005) * 0.005 AS lat_bin,
    COUNT(*) AS n
FROM commercial_places
GROUP BY lon_bin, lat_bin
ORDER BY n DESC
LIMIT 25;

-- 4. Nearest 10 places to Camden Yards (-76.6217, 39.2839)
SELECT
    name,
    category,
    ST_Distance(
        ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:3857'),
        ST_Transform(ST_Point(-76.6217, 39.2839), 'EPSG:4326', 'EPSG:3857')
    ) AS meters
FROM commercial_places
ORDER BY meters ASC
LIMIT 10;

-- 5. Full-text search (requires fts extension; built by load_duckdb.py)
-- Returns top 10 places matching the query "coffee"
SELECT id, name, category, address,
       fts_main_commercial_places.match_bm25(id, 'coffee') AS score
FROM commercial_places
WHERE score IS NOT NULL
ORDER BY score DESC
LIMIT 10;
