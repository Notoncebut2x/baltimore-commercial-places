/* Baltimore commercial-places map.
 * Loads places.geojson, renders clustered markers on a Leaflet map, and
 * populates the sidebar with business details when a marker is clicked.
 * Search + category filter rebuild the cluster layer in place.
 */
"use strict";

const BALTIMORE_CENTER = [39.2904, -76.6122];
const DEFAULT_ZOOM = 12;

const map = L.map("map", { preferCanvas: true }).setView(BALTIMORE_CENTER, DEFAULT_ZOOM);

L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
}).addTo(map);

const cluster = L.markerClusterGroup({
  chunkedLoading: true,
  showCoverageOnHover: false,
  spiderfyOnMaxZoom: true,
  maxClusterRadius: 50,
});
map.addLayer(cluster);

const detailEl = document.getElementById("detail");
const countEl = document.getElementById("count");
const searchEl = document.getElementById("search");
const categoryEl = document.getElementById("category-filter");

let allFeatures = [];
let activeMarker = null;

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

function prettyCategory(c) {
  if (!c) return "";
  return c.replace(/_/g, " ").replace(/\b\w/g, m => m.toUpperCase());
}

function row(label, value) {
  if (!value) return "";
  return `<dt>${label}</dt><dd>${value}</dd>`;
}

function linkify(url) {
  if (!url) return "";
  const safe = escapeHtml(url);
  return `<a href="${safe}" target="_blank" rel="noopener noreferrer">${safe}</a>`;
}

function telLink(phone) {
  if (!phone) return "";
  const safe = escapeHtml(phone);
  const digits = phone.replace(/[^0-9+]/g, "");
  return `<a href="tel:${digits}">${safe}</a>`;
}

function mailLink(email) {
  if (!email) return "";
  const safe = escapeHtml(email);
  return `<a href="mailto:${safe}">${safe}</a>`;
}

function renderDetail(props) {
  detailEl.classList.remove("empty");
  detailEl.innerHTML = `
    <h2>${escapeHtml(props.name ?? "(unnamed)")}</h2>
    <span class="category">${escapeHtml(prettyCategory(props.category))}</span>
    <dl>
      ${row("Group", escapeHtml(props.basic_category))}
      ${row("Subtype", escapeHtml(prettyCategory(props.subtype)))}
      ${row("Brand", escapeHtml(props.brand))}
      ${row("Address", escapeHtml(props.address))}
      ${row("ZIP", escapeHtml(props.postcode))}
      ${row("Phone", telLink(props.phone))}
      ${row("Email", mailLink(props.email))}
      ${row("Website", linkify(props.website))}
      ${row("Overture ID", `<code>${escapeHtml(props.id)}</code>`)}
    </dl>
  `;
}

function clearDetail() {
  detailEl.classList.add("empty");
  detailEl.innerHTML = `<p class="hint">Click a pin to see business details.</p>`;
}

function makeMarker(feature) {
  const [lon, lat] = feature.geometry.coordinates;
  const m = L.marker([lat, lon]);
  m.featureProps = feature.properties;
  m.bindTooltip(feature.properties.name ?? "(unnamed)", { direction: "top", offset: [-15, -10] });
  m.on("click", () => {
    activeMarker = m;
    renderDetail(feature.properties);
  });
  return m;
}

function rebuildLayer(features) {
  cluster.clearLayers();
  const markers = features.map(makeMarker);
  cluster.addLayers(markers);
  countEl.textContent = `${features.length.toLocaleString()} places`;
}

function applyFilters() {
  const q = searchEl.value.trim().toLowerCase();
  const cat = categoryEl.value;
  const filtered = allFeatures.filter(f => {
    const p = f.properties;
    if (cat && p.basic_category !== cat) return false;
    if (q) {
      const hay = `${p.name ?? ""} ${p.brand ?? ""} ${p.address ?? ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  rebuildLayer(filtered);
}

function populateCategoryFilter() {
  const counts = new Map();
  for (const f of allFeatures) {
    const c = f.properties.basic_category;
    if (!c) continue;
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (const [c, n] of sorted) {
    const opt = document.createElement("option");
    opt.value = c;
    opt.textContent = `${c} (${n.toLocaleString()})`;
    categoryEl.appendChild(opt);
  }
}

let searchTimer = null;
searchEl.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(applyFilters, 200);
});
categoryEl.addEventListener("change", applyFilters);

async function init() {
  try {
    const resp = await fetch("places.geojson");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const fc = await resp.json();
    allFeatures = fc.features ?? [];
    populateCategoryFilter();
    rebuildLayer(allFeatures);
    clearDetail();
  } catch (err) {
    countEl.textContent = "failed to load";
    detailEl.classList.add("empty");
    detailEl.innerHTML = `<p class="hint">Could not load places.geojson — run <code>python src/export_geojson.py</code> first. (${escapeHtml(err.message)})</p>`;
    console.error(err);
  }
}

init();
