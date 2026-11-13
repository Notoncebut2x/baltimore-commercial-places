-- Schema for the Baltimore commercial-places DuckDB database.
-- Re-runnable: uses CREATE TABLE IF NOT EXISTS / ADD COLUMN IF NOT EXISTS and
-- is paired with an upsert keyed on id in load_duckdb.py.

INSTALL spatial;
LOAD spatial;
INSTALL fts;
LOAD fts;

CREATE TABLE IF NOT EXISTS commercial_places (
    id                TEXT PRIMARY KEY,
    name              TEXT NOT NULL,
    category          TEXT,
    category_l1       TEXT,
    category_l2       TEXT,
    category_l3       TEXT,
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
    source_dataset    TEXT,
    confidence        DOUBLE,
    ingest_timestamp  TIMESTAMP WITH TIME ZONE NOT NULL,
    first_seen_at     TIMESTAMP WITH TIME ZONE,
    basic_category    TEXT,
    -- Updated on every run that still contains this id. Rows whose
    -- last_seen_at is older than the newest one are no longer in Overture
    -- (or no longer pass the filters) and are left out of the map export.
    last_seen_at      TIMESTAMP WITH TIME ZONE,
    last_seen_release TEXT
);

-- Migrations for DBs created before these columns existed. Safe to re-run.
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS first_seen_at  TIMESTAMP WITH TIME ZONE;
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS basic_category TEXT;
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS source_dataset TEXT;
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS confidence     DOUBLE;
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS category_l1    TEXT;
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS category_l2    TEXT;
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS category_l3    TEXT;
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS last_seen_at      TIMESTAMP WITH TIME ZONE;
ALTER TABLE commercial_places ADD COLUMN IF NOT EXISTS last_seen_release TEXT;

CREATE INDEX IF NOT EXISTS idx_commercial_places_category       ON commercial_places (category);
CREATE INDEX IF NOT EXISTS idx_commercial_places_basic_category ON commercial_places (basic_category);
CREATE INDEX IF NOT EXISTS idx_commercial_places_category_path  ON commercial_places (category_l1, category_l2, category_l3);
CREATE INDEX IF NOT EXISTS idx_commercial_places_postcode       ON commercial_places (postcode);
CREATE INDEX IF NOT EXISTS idx_commercial_places_brand          ON commercial_places (brand);
CREATE INDEX IF NOT EXISTS idx_commercial_places_lat_lon        ON commercial_places (latitude, longitude);
CREATE INDEX IF NOT EXISTS idx_commercial_places_first_seen_at  ON commercial_places (first_seen_at);
CREATE INDEX IF NOT EXISTS idx_commercial_places_last_seen_at   ON commercial_places (last_seen_at);

-- Places Overture marks operating_status = 'permanently_closed'. Same columns
-- as commercial_places plus when the closure was first detected. Never
-- exported to the map. A place that later reappears as open is moved back.
CREATE TABLE IF NOT EXISTS closed_places (
    id                 TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    category           TEXT,
    category_l1        TEXT,
    category_l2        TEXT,
    category_l3        TEXT,
    subtype            TEXT,
    address            TEXT,
    house_number       TEXT,
    street             TEXT,
    city               TEXT,
    state              TEXT,
    postcode           TEXT,
    country            TEXT,
    phone              TEXT,
    email              TEXT,
    website            TEXT,
    brand              TEXT,
    latitude           DOUBLE,
    longitude          DOUBLE,
    geometry_wkt       TEXT,
    source             TEXT NOT NULL,
    source_dataset     TEXT,
    confidence         DOUBLE,
    ingest_timestamp   TIMESTAMP WITH TIME ZONE NOT NULL,
    first_seen_at      TIMESTAMP WITH TIME ZONE,
    basic_category     TEXT,
    last_seen_at       TIMESTAMP WITH TIME ZONE,
    last_seen_release  TEXT,
    -- Overture release in which this place was first seen as closed.
    closed_release     TEXT,
    closed_detected_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_closed_places_closed_release ON closed_places (closed_release);
