---
# the default layout is 'page'
icon: fas fa-info-circle
order: 5
---

This site maps commercial and customer-facing places in Baltimore City:
shops, restaurants, services, health care, arts venues and more. The data
comes from the [Overture Maps](https://overturemaps.org/) Places theme and is
refreshed whenever Overture publishes a new release.

## How the data is built

A Python pipeline
([source on GitHub](https://github.com/Notoncebut2x/baltimore-commercial-places))
does the following:

1. Streams Overture Places from S3 with DuckDB, reading only the rows inside
   Baltimore's bounding box.
2. Flattens names, addresses, phones, websites, brands and the category
   taxonomy into plain columns.
3. Drops non-commercial branches of the taxonomy (government offices, parks,
   parking and so on) and splits off permanently closed places.
4. Keeps only places that fall inside the Baltimore City boundary, using the
   U.S. Census TIGER/Line polygon.
5. Loads the result into DuckDB and exports the current snapshot to GeoJSON
   for the map.

## Reading the map

- **Confidence** is Overture's 0–100 estimate that a place really exists at
  that spot. The map defaults to 90 and up; lower scores are more likely to be
  closed or duplicate listings.
- **New this release** shows places that first appeared in the most recent
  Overture release, as red pins.
- The **Table** view lists the same filtered places, and the export buttons
  download them as CSV or GeoJSON.

## Credits

Place data © [Overture Maps Foundation](https://overturemaps.org/) contributors.
Map tiles © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.
Site built with the [Chirpy](https://github.com/cotes2020/jekyll-theme-chirpy) Jekyll theme.
