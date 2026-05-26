# Baltimore Commercial Places ETL

A Python ETL pipeline that downloads commercial place data for Baltimore City
from [Overture Maps](https://overturemaps.org/) and loads it into a local
DuckDB database (`baltimore_commercial_places.duckdb`).

## What it does

1. Fetches the Baltimore City administrative boundary from the U.S. Census
   TIGER/Line 2024 places shapefile (cached as GeoJSON).
2. Streams the **Overture Places** theme from S3 with DuckDB + httpfs, pushing
   the Baltimore bounding box down as a predicate so only the relevant row
   groups are scanned (the global dataset is never materialised in memory).
3. Flattens nested Overture structs (`names`, `addresses`, `phones`,
   `websites`, `emails`, `categories`, `brand`) into scalar columns.
4. Filters to commercial / customer-facing categories
   (`eat_and_drink*`, `retail*`, `accommodation*`, …) and excludes
   government / infrastructure POIs.
5. Performs an exact polygon intersection against the Baltimore City
   boundary in EPSG:4326.
6. Upserts the result into `commercial_places` in DuckDB, with indexes,
   spatial extension support, and a full-text-search index over
   `name`, `brand`, `category`, and `address`.

Intermediate artifacts (`data/overture_places_raw.parquet`,
`data/commercial_places.parquet`) are kept on disk for debugging and to enable
fast partial reruns.

## Project layout

```
.
├── config.py                         # Paths, Overture release, bbox, category filter
├── requirements.txt
├── README.md
├── baltimore_commercial_places.duckdb (created on first run)
├── data/                              # boundary cache, parquet intermediates
├── logs/                              # pipeline.log
├── sql/
│   ├── schema.sql
│   ├── example_queries.sql
│   └── example_spatial_queries.sql
└── src/
    ├── __init__.py
    ├── main.py            # CLI entry point
    ├── download.py        # Overture S3 -> local raw parquet
    ├── transform.py       # flatten + category + polygon filters
    ├── load_duckdb.py     # apply schema, upsert, build FTS
    └── spatial_utils.py   # boundary fetch + intersection helpers
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Requires Python 3.10+. DuckDB will auto-install its `httpfs`, `spatial`, and
`fts` extensions on first run.

## Run

From the project root:

```bash
python src/main.py                  # full pipeline
python src/main.py --refresh-boundary   # re-download city boundary
python src/main.py --skip-download      # reuse cached raw Overture parquet
python src/main.py -v                   # DEBUG logging
```

Output:

```
baltimore_commercial_places.duckdb   # DuckDB database
logs/pipeline.log                    # structured run log
data/baltimore_boundary.geojson      # cached city polygon
data/overture_places_raw.parquet     # raw Overture rows (bbox)
data/commercial_places.parquet       # cleaned/filtered rows
```

## Pointing at a newer Overture release

Overture publishes monthly. Override the release at runtime:

```bash
OVERTURE_RELEASE=2025-04-23.0 python src/main.py
```

or edit `OVERTURE_RELEASE` in `config.py`. The loader upserts on `id`, so a
fresh release updates changed rows and appends new ones in place.

## Example queries

Open the database with the DuckDB CLI:

```bash
duckdb baltimore_commercial_places.duckdb
```

```sql
-- Restaurants with websites
SELECT name, category, website
FROM commercial_places
WHERE category LIKE 'eat_and_drink%';

-- Places within ~500 m of downtown
LOAD spatial;
SELECT name
FROM commercial_places
WHERE ST_DWithin(
    ST_Transform(ST_Point(longitude, latitude), 'EPSG:4326', 'EPSG:3857'),
    ST_Transform(ST_Point(-76.6122, 39.2904), 'EPSG:4326', 'EPSG:3857'),
    500
);
```

More examples in `sql/example_queries.sql` and `sql/example_spatial_queries.sql`.

### Export to GeoParquet

```sql
LOAD spatial;
COPY (
    SELECT *, ST_Point(longitude, latitude) AS geometry
    FROM commercial_places
) TO 'commercial_places.geoparquet'
WITH (FORMAT 'parquet');
```

## Scheduling updates

Run on the first day of every month (after Overture's typical release cadence)
via cron:

```cron
0 7 1 * *  cd /path/to/biz_info && /path/to/.venv/bin/python src/main.py >> logs/cron.log 2>&1
```

Or with `systemd`:

```ini
# /etc/systemd/system/overture-baltimore.service
[Service]
Type=oneshot
WorkingDirectory=/path/to/biz_info
ExecStart=/path/to/.venv/bin/python src/main.py

# /etc/systemd/system/overture-baltimore.timer
[Timer]
OnCalendar=monthly
Persistent=true
[Install]
WantedBy=timers.target
```

The pipeline is idempotent (upserts on `id`), so running it more frequently
than Overture's release cadence is harmless.

## Data source & license

- **Overture Maps Foundation – Places theme**, distributed under
  [CDLA-Permissive-2.0](https://overturemaps.org/community/licensing/).
- **U.S. Census TIGER/Line 2024 Places** – public domain.

This pipeline never scrapes proprietary sources.
