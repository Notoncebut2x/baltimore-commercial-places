/* Baltimore commercial-places map.
 * Loads places.geojson, renders clustered markers on a Leaflet map, and
 * populates the sidebar with business details when a marker is clicked.
 * Search + a three-level taxonomy filter (e.g. Food And Drink > Restaurant >
 * Asian Restaurant) rebuild the cluster layer in place.
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
// One <select> per taxonomy level, matching category_l1..category_l3.
const LEVELS = [
  { prop: "category_l1", el: document.getElementById("category-l1"), all: "All categories" },
  { prop: "category_l2", el: document.getElementById("category-l2"), all: "All subcategories" },
  { prop: "category_l3", el: document.getElementById("category-l3"), all: "All sub-subcategories" },
];
const newnessEl = document.getElementById("newness-filter");
// Confidence slider works in 0-100; the data stores Overture's 0-1 score.
const confidenceEl = document.getElementById("confidence-filter");
const confidenceValueEl = document.getElementById("confidence-value");

// Red pin used when the "New this release" filter is active. Inline SVG so
// the front-end stays self-contained (no external image assets).
const NEW_ICON = L.divIcon({
  className: "new-marker",
  html: `<svg width="24" height="36" viewBox="0 0 24 36" xmlns="http://www.w3.org/2000/svg">
    <path d="M12 0C5.373 0 0 5.373 0 12c0 9 12 24 12 24s12-15 12-24c0-6.627-5.373-12-12-12z" fill="#dc2626" stroke="white" stroke-width="1.5"/>
    <circle cx="12" cy="12" r="4.5" fill="white"/>
  </svg>`,
  iconSize: [24, 36],
  iconAnchor: [12, 36],
  popupAnchor: [0, -36],
});

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

function formatDate(s) {
  if (!s) return "";
  return String(s).slice(0, 10);
}

function categoryPath(props) {
  return LEVELS.map(l => props[l.prop]).filter(Boolean).map(prettyCategory).join(" › ");
}

function renderDetail(props) {
  detailEl.classList.remove("empty");
  const newBadge = props.is_new ? `<span class="new-badge">NEW</span>` : "";
  detailEl.innerHTML = `
    <h2>${escapeHtml(props.name ?? "(unnamed)")} ${newBadge}</h2>
    <span class="category">${escapeHtml(prettyCategory(props.category))}</span>
    <dl>
      ${row("Taxonomy", escapeHtml(categoryPath(props)))}
      ${row("Group", escapeHtml(prettyCategory(props.basic_category)))}
      ${row("Subtype", escapeHtml(prettyCategory(props.subtype)))}
      ${row("Brand", escapeHtml(props.brand))}
      ${row("Address", escapeHtml(props.address))}
      ${row("ZIP", escapeHtml(props.postcode))}
      ${row("Phone", telLink(props.phone))}
      ${row("Email", mailLink(props.email))}
      ${row("Website", linkify(props.website))}
      ${row("Data source", escapeHtml(props.source_dataset))}
      ${row("Confidence", props.confidence == null ? "" : Math.round(props.confidence * 100))}
      ${row("First seen", escapeHtml(formatDate(props.first_seen_at)))}
      ${row("Overture ID", `<code>${escapeHtml(props.id)}</code>`)}
    </dl>
  `;
}

function clearDetail() {
  detailEl.classList.add("empty");
  detailEl.innerHTML = `<p class="hint">Click a pin to see business details.</p>`;
}

function makeMarker(feature, useRedPin) {
  const [lon, lat] = feature.geometry.coordinates;
  const opts = useRedPin ? { icon: NEW_ICON } : undefined;
  const m = L.marker([lat, lon], opts);
  m.featureProps = feature.properties;
  m.bindTooltip(feature.properties.name ?? "(unnamed)", { direction: "top", offset: [-15, -10] });
  m.on("click", () => {
    activeMarker = m;
    renderDetail(feature.properties);
  });
  return m;
}

function rebuildLayer(features, useRedPins) {
  cluster.clearLayers();
  const markers = features.map(f => makeMarker(f, useRedPins));
  cluster.addLayers(markers);
  countEl.textContent = `${features.length.toLocaleString()} places`;
}

function applyFilters() {
  const q = searchEl.value.trim().toLowerCase();
  const newness = newnessEl.value;
  const minConfidence = Number(confidenceEl.value);
  const filtered = allFeatures.filter(f => {
    const p = f.properties;
    if (newness === "new" && !p.is_new) return false;
    if (minConfidence > 0 && !(p.confidence * 100 >= minConfidence)) return false;
    if (!matchesCategory(p, LEVELS.length)) return false;
    if (q) {
      const hay = `${p.name ?? ""} ${p.brand ?? ""} ${p.address ?? ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  rebuildLayer(filtered, newness === "new");
}

// True if the feature matches the selected value at every level above `depth`.
function matchesCategory(p, depth) {
  for (let i = 0; i < depth; i++) {
    const v = LEVELS[i].el.value;
    if (v && p[LEVELS[i].prop] !== v) return false;
  }
  return true;
}

// Rebuild the options for level `i` from features matching the levels above
// it. A level is disabled until its parent has a value, or if no feature
// under that parent goes that deep.
function populateLevel(i) {
  const { prop, el, all } = LEVELS[i];
  el.innerHTML = "";
  el.appendChild(new Option(all, ""));
  if (i > 0 && !LEVELS[i - 1].el.value) {
    el.disabled = true;
    return;
  }
  const counts = new Map();
  for (const f of allFeatures) {
    const c = f.properties[prop];
    if (!c || !matchesCategory(f.properties, i)) continue;
    counts.set(c, (counts.get(c) ?? 0) + 1);
  }
  const sorted = [...counts.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  for (const [c, n] of sorted) {
    el.appendChild(new Option(`${prettyCategory(c)} (${n.toLocaleString()})`, c));
  }
  el.disabled = counts.size === 0;
}

// Changing a level resets and repopulates every level below it.
function onCategoryChange(i) {
  for (let j = i + 1; j < LEVELS.length; j++) populateLevel(j);
  applyFilters();
}

let searchTimer = null;
searchEl.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(applyFilters, 200);
});
LEVELS.forEach((l, i) => l.el.addEventListener("change", () => onCategoryChange(i)));
newnessEl.addEventListener("change", applyFilters);
// Update the label live while dragging; rebuild markers only on release.
confidenceEl.addEventListener("input", () => {
  confidenceValueEl.textContent = confidenceEl.value;
});
confidenceEl.addEventListener("change", applyFilters);

async function init() {
  try {
    const resp = await fetch("places.geojson");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const fc = await resp.json();
    allFeatures = fc.features ?? [];
    LEVELS.forEach((_, i) => populateLevel(i));
    applyFilters();
    clearDetail();
  } catch (err) {
    countEl.textContent = "failed to load";
    detailEl.classList.add("empty");
    detailEl.innerHTML = `<p class="hint">Could not load places.geojson — run <code>python src/export_geojson.py</code> first. (${escapeHtml(err.message)})</p>`;
    console.error(err);
  }
}

init();
