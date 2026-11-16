---
title: Mapping Baltimore's commercial places
date: 2026-11-16 12:00:00 -0500
categories: [Data, Baltimore]
tags: [overture, maps, duckdb]
---

The [map]({{ '/map/' | relative_url }}) on this site shows the shops,
restaurants and services across Baltimore City, built from
[Overture Maps](https://overturemaps.org/) open data.

## What you can do

- **Search** by business name, brand or street address.
- **Filter** through three levels of Overture's category taxonomy, for example
  *Food And Drink › Restaurant › Asian Restaurant*.
- **Set a confidence threshold.** Overture scores each place on how likely it
  is to exist. The map starts at 90+, which removes most stale and duplicate
  listings.
- **Spot new businesses.** "New this release" shows only places that first
  appeared in the latest Overture release.
- **Switch to a table** to sort by any column, then **export** the filtered
  list as CSV for spreadsheets or GeoJSON for GIS tools.

## Where the data comes from

Overture combines place data from several sources (Meta, BrightQuery,
Microsoft, Foursquare and others) into one open dataset with a shared category taxonomy. A
small [Python and DuckDB pipeline](https://github.com/Notoncebut2x/baltimore-commercial-places)
pulls the Baltimore slice, keeps the commercial categories, clips it to the
city boundary and tracks when each place first appeared. See the
[About]({{ '/about/' | relative_url }}) page for the details.
