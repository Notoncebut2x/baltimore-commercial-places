/* Baltimore commercial-places map.
 * Loads places.geojson, renders clustered markers on a Leaflet map, and
 * populates the sidebar with business details when a marker is clicked.
 * Search + a three-level taxonomy filter (e.g. Food And Drink > Restaurant >
 * Asian Restaurant) rebuild the cluster layer in place. The same filtered
 * set drives a sortable, paginated table view and CSV/GeoJSON export.
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
let filteredFeatures = [];
let activeMarker = null;
// Marker for each currently-filtered feature, keyed by Overture ID, so a
// table row can locate its pin.
let markersById = new Map();

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
  markersById = new Map(markers.map(m => [m.featureProps.id, m]));
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
  filteredFeatures = filtered;
  rebuildLayer(filtered, newness === "new");
  tablePage = 0;
  renderTable();
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

// ---- Map / table view ------------------------------------------------------

const tableViewEl = document.getElementById("table-view");
const mapEl = document.getElementById("map");
const theadEl = document.querySelector("#places-table thead");
const tbodyEl = document.querySelector("#places-table tbody");
const pageInfoEl = document.getElementById("page-info");
const pagePrevEl = document.getElementById("page-prev");
const pageNextEl = document.getElementById("page-next");
const tabEls = document.querySelectorAll("#view-tabs [data-view]");

const PAGE_SIZE = 100;
// `value` is the raw sort key; `render` returns cell HTML (defaults to the
// escaped value).
const TABLE_COLUMNS = [
  { key: "name", label: "Name", value: p => (p.name ?? "").trim(),
    render: p => escapeHtml(p.name ?? "(unnamed)") + (p.is_new ? ` <span class="new-badge">NEW</span>` : "") },
  { key: "category", label: "Category", value: p => categoryPath(p) },
  { key: "address", label: "Address", value: p => p.address ?? "" },
  { key: "postcode", label: "ZIP", value: p => p.postcode ?? "" },
  { key: "phone", label: "Phone", value: p => p.phone ?? "", render: p => telLink(p.phone) },
  { key: "website", label: "Website", value: p => p.website ?? "", render: p => linkify(p.website) },
  { key: "confidence", label: "Conf.", numeric: true,
    value: p => p.confidence ?? -1,
    render: p => p.confidence == null ? "" : String(Math.round(p.confidence * 100)) },
  { key: "first_seen_at", label: "First seen", value: p => p.first_seen_at ?? "" },
];

let currentView = "map";
let tablePage = 0;
let sortKey = "name";
let sortDir = 1;  // 1 ascending, -1 descending

function sortedFeatures() {
  const col = TABLE_COLUMNS.find(c => c.key === sortKey);
  const cmp = col.numeric
    ? (a, b) => a - b
    : (a, b) => a.localeCompare(b, undefined, { sensitivity: "base" });
  return [...filteredFeatures].sort((fa, fb) => {
    const a = col.value(fa.properties), b = col.value(fb.properties);
    // Empty strings sort last regardless of direction.
    if (!col.numeric && (a === "") !== (b === "")) return a === "" ? 1 : -1;
    return sortDir * cmp(a, b);
  });
}

function renderTableHead() {
  theadEl.innerHTML = `<tr>${TABLE_COLUMNS.map(c => {
    const arrow = c.key === sortKey ? (sortDir === 1 ? " ▲" : " ▼") : "";
    const aria = c.key === sortKey ? (sortDir === 1 ? "ascending" : "descending") : "none";
    return `<th data-key="${c.key}" aria-sort="${aria}"${c.numeric ? ' class="num"' : ""}>${c.label}${arrow}</th>`;
  }).join("")}<th></th></tr>`;
}

function renderTable() {
  if (currentView !== "table") return;
  renderTableHead();
  const rows = sortedFeatures();
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  tablePage = Math.min(tablePage, pages - 1);
  const start = tablePage * PAGE_SIZE;
  const pageRows = rows.slice(start, start + PAGE_SIZE);

  tbodyEl.innerHTML = pageRows.map(f => {
    const p = f.properties;
    const cells = TABLE_COLUMNS.map(c => {
      const html = c.render ? c.render(p) : escapeHtml(c.value(p));
      return `<td${c.numeric ? ' class="num"' : ""}>${html}</td>`;
    }).join("");
    return `<tr data-id="${escapeHtml(p.id)}">${cells}` +
      `<td><button type="button" class="locate">Map</button></td></tr>`;
  }).join("") || `<tr><td colspan="${TABLE_COLUMNS.length + 1}" class="hint">No places match the current filters.</td></tr>`;

  pageInfoEl.textContent = rows.length
    ? `${(start + 1).toLocaleString()}–${(start + pageRows.length).toLocaleString()} of ${rows.length.toLocaleString()}`
    : "0 places";
  pagePrevEl.disabled = tablePage === 0;
  pageNextEl.disabled = tablePage >= pages - 1;
}

function setView(view) {
  currentView = view;
  tabEls.forEach(t => t.setAttribute("aria-selected", String(t.dataset.view === view)));
  mapEl.hidden = view !== "map";
  tableViewEl.hidden = view !== "table";
  if (view === "map") map.invalidateSize();
  else renderTable();
}

function locateOnMap(id) {
  const m = markersById.get(id);
  if (!m) return;
  setView("map");
  activeMarker = m;
  renderDetail(m.featureProps);
  cluster.zoomToShowLayer(m, () => m.openTooltip());
}

tabEls.forEach(t => t.addEventListener("click", () => setView(t.dataset.view)));
theadEl.addEventListener("click", e => {
  const th = e.target.closest("th[data-key]");
  if (!th) return;
  if (th.dataset.key === sortKey) sortDir = -sortDir;
  else { sortKey = th.dataset.key; sortDir = 1; }
  tablePage = 0;
  renderTable();
});
tbodyEl.addEventListener("click", e => {
  const tr = e.target.closest("tr[data-id]");
  if (!tr || e.target.closest("a")) return;
  if (e.target.closest(".locate")) { locateOnMap(tr.dataset.id); return; }
  tbodyEl.querySelector("tr.selected")?.classList.remove("selected");
  tr.classList.add("selected");
  renderDetail(markersById.get(tr.dataset.id).featureProps);
});
pagePrevEl.addEventListener("click", () => { tablePage--; renderTable(); tableViewEl.querySelector(".table-scroll").scrollTop = 0; });
pageNextEl.addEventListener("click", () => { tablePage++; renderTable(); tableViewEl.querySelector(".table-scroll").scrollTop = 0; });

// ---- Export -----------------------------------------------------------------

const EXPORT_COLUMNS = [
  "id", "name", "category", "category_l1", "category_l2", "category_l3",
  "basic_category", "subtype", "brand", "address", "postcode", "phone",
  "email", "website", "source_dataset", "confidence", "first_seen_at", "is_new",
];

// Quote every field, and neutralise values a spreadsheet would run as a
// formula. Phone numbers like "+1 410…" are left alone.
function csvCell(v) {
  let s = v == null ? "" : String(v);
  if (/^[=@\t\r]/.test(s) || /^[+-][^0-9 (]/.test(s)) s = "'" + s;
  return `"${s.replace(/"/g, '""')}"`;
}

function download(filename, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function exportBasename() {
  return `baltimore-places-${new Date().toISOString().slice(0, 10)}`;
}

function exportCsv() {
  const header = [...EXPORT_COLUMNS, "latitude", "longitude"];
  const lines = [header.map(csvCell).join(",")];
  for (const f of sortedFeatures()) {
    const p = f.properties;
    const [lon, lat] = f.geometry.coordinates;
    lines.push([...EXPORT_COLUMNS.map(k => k === "is_new" ? Boolean(p.is_new) : p[k]), lat, lon]
      .map(csvCell).join(","));
  }
  // BOM so Excel opens it as UTF-8.
  download(`${exportBasename()}.csv`, "\uFEFF" + lines.join("\r\n"), "text/csv;charset=utf-8");
}

function exportGeojson() {
  const fc = { type: "FeatureCollection", features: sortedFeatures() };
  download(`${exportBasename()}.geojson`, JSON.stringify(fc), "application/geo+json");
}

document.getElementById("export-csv").addEventListener("click", exportCsv);
document.getElementById("export-geojson").addEventListener("click", exportGeojson);

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
