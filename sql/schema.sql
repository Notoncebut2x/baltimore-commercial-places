-- Schema for the Baltimore commercial-places DuckDB database.
-- Re-runnable: uses CREATE TABLE IF NOT EXISTS and is paired with
-- a TRUNCATE-then-INSERT in load_duckdb.py for idempotent reruns.

INSTALL spatial;
LOAD spatial;
INSTALL fts;
LOAD fts;

CREATE TABLE IF NOT EXISTS commercial_places (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    category          TEXT,
    subtype           TEXT,
    address           TEXT,
    house_number      TEXT,
    street            TEXT,
    city              TEXT,
    state             TEXT,
    postcode          TEXT,
    country           TEXT,
    phone             TEXT,
    email             TEXT,
    website           TEXT,
    brand             TEXT,
    latitude          DOUBLE,
    longitude         DOUBLE,
    geometry_wkt      TEXT,
    source            TEXT NOT NULL,
    ingest_timestamp  TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_commercial_places_category ON commercial_places (category);
CREATE INDEX IF NOT EXISTS idx_commercial_places_postcode ON commercial_places (postcode);
CREATE INDEX IF NOT EXISTS idx_commercial_places_brand    ON commercial_places (brand);
CREATE INDEX IF NOT EXISTS idx_commercial_places_lat_lon  ON commercial_places (latitude, longitude);
