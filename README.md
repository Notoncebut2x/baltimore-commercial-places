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
   `websites`, `emails`, `taxonomy`, `brand`) into scalar columns, including
   the top three taxonomy levels as `category_l1`–`category_l3`.
4. Filters to commercial / customer-facing places by excluding taxonomy
   branches such as government offices, parks and parking (see
   [Editing the category filter](#editing-the-category-filter)), and splits
   off permanently closed places.
5. Performs an exact polygon intersection against the Baltimore City
   boundary in EPSG:4326.
6. Upserts open places into `commercial_places` and closed places into
   `closed_places` in DuckDB, with indexes,
   spatial extension support, and a full-text-search index over
   `name`, `brand`, `category`, and `address`.

Intermediate artifacts (`data/raw/overture_places_<release>.parquet`,
`data/commercial_places.parquet`, `data/closed_places.parquet`) are kept on disk for debugging and to enable
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

## Run the ETL pipeline

From the project root:

```bash
python src/main.py                  # full pipeline on the latest Overture release
python src/main.py --refresh-boundary   # re-download city boundary
python src/main.py --skip-download      # don't check for a new release; reuse newest in data/raw/
python src/main.py --release 2026-09-23.0   # process a specific release
python src/main.py -v                   # DEBUG logging
```

Output:

```
baltimore_commercial_places.duckdb   # DuckDB database
logs/pipeline.log                    # structured run log
data/baltimore_boundary.geojson      # cached city polygon
data/raw/overture_places_<release>.parquet  # raw Overture rows (bbox), one file per release
data/commercial_places.parquet       # cleaned/filtered rows
```

## Run the map UI (frontend)

The frontend (`web/`) is a static Leaflet map that reads `web/places.geojson`.
From the project root, with the virtualenv active (`source .venv/bin/activate`):

1. Export the latest GeoJSON from DuckDB. `src/main.py` does **not** do this,
   so re-run it after every pipeline run or the map will show stale data:

   ```bash
   python src/export_geojson.py                       # threshold = MIN_CONFIDENCE in config.py
   python src/export_geojson.py --min-confidence 0.8  # only places with confidence >= 0.8
   python src/export_geojson.py --min-confidence 0    # no confidence filter
   ```

   `--min-confidence` takes a value from 0 to 1 and only affects what goes on
   the map; the DuckDB table is left unchanged.

2. Serve the `web/` directory over HTTP — browsers won't `fetch()` it directly
   from `file://`:

   ```bash
   python -m http.server 8000 --directory web
   ```

   Then open <http://localhost:8000>. Stop the server with Ctrl+C.

## Publish the map to GitHub Pages

The public site (<https://notoncebut2x.github.io/baltimore-commercial-places/>)
is a [Chirpy](https://github.com/cotes2020/jekyll-theme-chirpy) Jekyll site in
`site/`. The Pages workflow (`.github/workflows/deploy-pages.yml`) builds it and
copies the map from `web/` to `/app/`, which the site's Map tab embeds. Edit
the About page in `site/_tabs/about.md` and add posts under `site/_posts/`.

`web/places.geojson` isn't committed (it's ~14 MB and changes every refresh).
Instead it's uploaded as an asset on a GitHub Release tagged `map-data`, and
the Pages workflow (`.github/workflows/deploy-pages.yml`) downloads it at
deploy time. After exporting:

```bash
python src/publish_map_data.py              # upload places.geojson + redeploy the site
python src/publish_map_data.py --no-deploy  # upload only
gh run watch                                # follow the deploy
```

This needs the GitHub CLI (`gh`) logged in with push access. Pushing changes
under `web/` or `site/` to `main` also redeploys, using whatever file was last
uploaded.

## Editing the category filter

The commercial filter works on Overture's category taxonomy
(`taxonomy.hierarchy`), e.g. `food_and_drink/restaurant/asian_restaurant`.
Everything is kept except the branches listed in `EXCLUDED_TAXONOMY_PATHS` in
`config.py`. Each entry drops that node and everything under it:

```python
EXCLUDED_TAXONOMY_PATHS = (
    "community_and_government/government_office",
    "sports_and_recreation/park",          # parks, playgrounds, dog parks...
    "geographic_entities",                 # a whole top-level branch
    ...
)
```

Places with no taxonomy at all are dropped. The `basic_category` column
("Group" in the map's detail panel) is Overture's own coarse grouping, and
the map's category dropdowns use the first three taxonomy levels
(`category_l1`–`category_l3`). Valid branch names are listed in the
[Overture places guide](https://docs.overturemaps.org/guides/places/).

After editing the list, re-filter without re-downloading:

```bash
python src/main.py --skip-download
python src/export_geojson.py   # refresh the map UI's data
```

## Closed places and stale rows

- **Permanently closed places** (Overture `operating_status =
  'permanently_closed'`) go to a separate `closed_places` table and are never
  exported to the map. `closed_release` records the Overture release in which
  the closure was first seen, and `closed_detected_at` when the pipeline
  picked it up. If a place was on the map before, it is moved out of
  `commercial_places` and keeps its `first_seen_at`. If a later release lists
  it as open again, it is moved back.
- **Stale rows.** Each run stamps `last_seen_at` / `last_seen_release` on every
  place it contains. Places that drop out of Overture, or stop passing the
  filters, stay in `commercial_places` for history but keep their old
  `last_seen_at`, and the map export only includes rows from the latest run.

The release comes from the raw file's name in `data/raw/`.

```sql
-- Closures by release
SELECT closed_release, COUNT(*) FROM closed_places GROUP BY 1 ORDER BY 1;

-- Places no longer in the latest run
SELECT name, last_seen_release FROM commercial_places
WHERE last_seen_at < (SELECT MAX(last_seen_at) FROM commercial_places);
```

## Per-row data provenance

Each row carries a `source_dataset` column naming the upstream dataset that
contributed it to Overture — e.g. `meta`, `Microsoft`, `Foursquare`,
`BrightQuery`, `AllThePlaces`. It's extracted from the Overture `sources`
struct array (the entry whose `property` is empty, which describes the
record as a whole, not a single field). The detail panel in the map UI
shows it as "Data source".

```sql
SELECT source_dataset, COUNT(*) AS n
FROM commercial_places
GROUP BY 1 ORDER BY n DESC;
```

## Detecting new businesses across runs

Each row carries a `first_seen_at` timestamp. It's set the first time an
Overture `id` shows up in the load and is preserved on subsequent upserts,
so the column reflects when the business was first observed — not when it
was last refreshed (which is `ingest_timestamp`).

The loader logs the new-id count every run:

```
load_duckdb new businesses since previous run: 142
```

Query "what's new in the most recent run":

```sql
SELECT name, category, address, first_seen_at
FROM commercial_places
WHERE first_seen_at = (SELECT MAX(first_seen_at) FROM commercial_places)
ORDER BY category, name;
```

See `sql/example_queries.sql` queries 6–7 for more.

## Overture releases

Overture publishes monthly, and `python src/main.py` always downloads the
latest release. Each release is saved as its own file,
`data/raw/overture_places_<release>.parquet`, and older files are never
deleted. That matters because Overture removes releases from S3 after about
60 days, so your local copies are the only way to re-run an old release.
A release that's already in `data/raw/` isn't downloaded again.

To process a specific release:

```bash
python src/main.py --release 2026-09-23.0
```

This uses the local copy if there is one, otherwise it tries to download it.
You can also pin a release with `OVERTURE_RELEASE` (env var or `config.py`).
The loader upserts on `id`, so a fresh release updates changed rows and
appends new ones in place. Process releases in date order: whichever run is
most recent becomes the map's current snapshot.

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
