---
icon: fas fa-map-location-dot
order: 1
---

Search by name, brand or address, narrow by category, and switch to the
**Table** tab to sort the results or export them as CSV or GeoJSON.

<iframe class="places-map" src="{{ '/map/' | relative_url }}" title="Baltimore commercial places map" loading="lazy"></iframe>

<a href="{{ '/map/' | relative_url }}" target="_blank" rel="noopener">Open the map full screen <i class="fas fa-up-right-from-square fa-xs"></i></a>

<style>
  .places-map {
    width: 100%;
    height: 75vh;
    min-height: 480px;
    margin-bottom: 0.75rem;
    border: 1px solid var(--main-border-color);
    border-radius: 0.5rem;
  }
</style>
