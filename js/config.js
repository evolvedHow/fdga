/**
 * config.js — Fair Districts GA Map Configuration
 * =================================================
 * Single source of truth for all map data sources, layer definitions,
 * and demographic color scales. To add a new district map, add one
 * entry to DISTRICT_MAPS. Everything else is data-driven.
 */

// Must be var (not const/let) so it attaches to window and is visible to map.js
var FDGA = window.FDGA || {};

// ── Mapbox token (loaded from the page or environment) ────────────────────────
// Set window.MAPBOX_TOKEN before this script, or it falls back to the
// obfuscated value injected by the server at /js/config.js
FDGA.token = window.MAPBOX_TOKEN || null;

// ── District map definitions ──────────────────────────────────────────────────
// Each entry: { id, label, chamber, version, file }
// 'file' is relative to /data/ — served by FastAPI's static mount
FDGA.DISTRICT_MAPS = [
  // Senate
  { id: 'senate',    chamber: 'senate',   version: 'enacted_2014', label: 'Senate 2014',          file: 'senate14_census20.geojson' },
  { id: 'senate_p1', chamber: 'senate',   version: 'proposed_dem', label: 'Senate Proposed (Dem)', file: 'senate_prop1_dem.geojson' },
  { id: 'senate_p2', chamber: 'senate',   version: 'proposed_rep', label: 'Senate Proposed (Rep)', file: 'senate_prop2_rep.geojson' },
  { id: 'senate_p3', chamber: 'senate',   version: 'enacted_2021', label: 'Senate 2021 Enacted',   file: 'senate_enacted_2123_2024update.geojson' },
  { id: 'senate_r1', chamber: 'senate',   version: 'enacted_2024', label: 'Senate 2024 Enacted',   file: 'senate_enacted_24_2024update.geojson' },
  { id: 'senate_r2', chamber: 'senate',   version: 'remedy_2',     label: 'Senate Remedy 2',       file: 'senate_remedy_2.geojson' },
  // House
  { id: 'house',     chamber: 'house',    version: 'enacted_2015', label: 'House 2015',            file: 'house15_census20.geojson' },
  { id: 'house_p1',  chamber: 'house',    version: 'proposed_dem', label: 'House Proposed (Dem)',  file: 'house_prop1_dem.geojson' },
  { id: 'house_p2',  chamber: 'house',    version: 'proposed_rep', label: 'House Proposed (Rep)',  file: 'house_prop2_rep.geojson' },
  { id: 'house_p3',  chamber: 'house',    version: 'enacted_2021', label: 'House 2021 Enacted',    file: 'house_enacted_2123_2024update.geojson' },
  { id: 'house_r1',  chamber: 'house',    version: 'enacted_2024', label: 'House 2024 Enacted',    file: 'house_enacted_24_2024update.geojson' },
  { id: 'house_r2',  chamber: 'house',    version: 'remedy_2',     label: 'House Remedy 2',        file: 'house_remedy_2.geojson' },
  // Congress
  { id: 'congress',             chamber: 'congress', version: 'enacted_2012', label: 'Congress 2012',           file: 'congress12_census20.geojson' },
  { id: 'congress_proposed',    chamber: 'congress', version: 'enacted_2021', label: 'Congress 2021 Enacted',   file: 'congress21_census20.geojson' },
  { id: 'congress_proposed_2',  chamber: 'congress', version: 'proposed_dem', label: 'Congress Proposed (Dem)', file: 'congress21_p2.geojson' },
  { id: 'congress_proposed_3',  chamber: 'congress', version: 'enacted_2023', label: 'Congress 2023 Enacted',   file: 'congress_enacted_2123_2024update.geojson' },
  { id: 'congress_r1',          chamber: 'congress', version: 'enacted_2024', label: 'Congress 2024 Enacted',   file: 'congress_enacted_24_2024update.geojson' },
  { id: 'congress_r2',          chamber: 'congress', version: 'remedy_2',     label: 'Congress Remedy 2',       file: 'congress_remedy_2.geojson' },
];

// ── Boundary overlay sources ───────────────────────────────────────────────────
FDGA.BOUNDARY_SOURCES = {
  counties: { type: 'geojson', data: '/data/county.geojson' },
  cities:   { type: 'geojson', data: '/data/places_2020data.geojson' },
};

// ── Demographic field definitions ─────────────────────────────────────────────
// 'prop' = the GeoJSON property name (raw, 0.0–1.0 range)
// 'label' = human-readable label for tooltip and legend
FDGA.DEMOGRAPHICS = {
  pct_bvp: { prop: 'pct_bvp', label: 'Black VAP %',    unit: '%' },
  pct_hvp: { prop: 'pct_hvp', label: 'Hispanic VAP %', unit: '%' },
  pct_avp: { prop: 'pct_avp', label: 'Asian VAP %',    unit: '%' },
  pct_bp_: { prop: 'pct_bp_', label: 'Minority VAP %', unit: '%' },
  partisan:{ prop: 'partisan',label: 'Partisan Lean (% Dem)', unit: '%' },
};

// ── Color scales (value range 0.0–1.0) ────────────────────────────────────────
// Each entry: [stopValue, color]
// Values > 1.0 stop catches missing data → grey
FDGA.COLORS = {
  pct_bvp: [
    [0,     '#f2f0f7'],
    [0.10,  '#cbc9e2'],
    [0.25,  '#9e9ac8'],
    [0.50,  '#756bb1'],
    [0.75,  '#54278f'],
    [1.01,  '#d4d5d5'],
  ],
  pct_hvp: [
    [0,     '#feedde'],
    [0.10,  '#fdbe85'],
    [0.25,  '#fd8d3c'],
    [0.50,  '#e6550d'],
    [0.75,  '#a63603'],
    [1.01,  '#d4d5d5'],
  ],
  pct_avp: [
    [0,     '#edf8e9'],
    [0.10,  '#bae4b3'],
    [0.25,  '#74c476'],
    [0.50,  '#31a354'],
    [0.75,  '#006d2c'],
    [1.01,  '#d4d5d5'],
  ],
  pct_bp_: [
    [0,     '#feebe2'],
    [0.10,  '#fcc5c0'],
    [0.25,  '#f768a1'],
    [0.50,  '#c51b8a'],
    [0.75,  '#7a0177'],
    [1.01,  '#d4d5d5'],
  ],
  partisan: [
    [0,     '#d62728'],  // strongly Republican
    [0.40,  '#fc8d59'],
    [0.465, '#fee090'],
    [0.50,  '#a8a8d8'],  // toss-up
    [0.535, '#91bfdb'],
    [0.60,  '#4575b4'],
    [1.01,  '#d4d5d5'],  // strongly Democrat
  ],
};

// ── Legend labels ─────────────────────────────────────────────────────────────
FDGA.LEGEND_LABELS = {
  pct_bvp:  ['0%', '10%', '25%', '50%', '75%+'],
  pct_hvp:  ['0%', '10%', '25%', '50%', '75%+'],
  pct_avp:  ['0%', '10%', '25%', '50%', '75%+'],
  pct_bp_:  ['0%', '10%', '25%', '50%', '75%+'],
  partisan: ['Strong R', 'Lean R', 'Toss-up', 'Lean D', 'Strong D'],
};