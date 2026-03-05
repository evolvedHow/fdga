/**
 * map.js — Fair Districts GA Interactive Map
 * ============================================
 * Data-driven Mapbox GL JS map. Replaces the old hard-coded
 * main.js + sources.layers.js with a config-driven approach.
 *
 * Key fixes vs old code:
 *  - Hover filter uses 'DISTRICT' (uppercase) consistently
 *  - Partisan values displayed correctly (already 0–1, multiply ×100 once)
 *  - Single mousemove/mouseleave handler pair instead of 18 copies
 *  - All sources and layers generated from FDGA.DISTRICT_MAPS config
 */

(function () {
  'use strict';

  // ── Config constants ──────────────────────────────────────────────────────────
  const DEFAULT_MAP_ID = 'senate_r1';
  const POPUP_LAYER_IDS = FDGA.DISTRICT_MAPS.map(dm => `${dm.id}_popup`);

  // ── State ────────────────────────────────────────────────────────────────────
  let currentMapId  = DEFAULT_MAP_ID; // which district map is active
  let currentMeasure = '';            // which demographic overlay is active
  let showFill    = false;
  let showCounty  = false;
  let showCity    = false;
  let lockedDistrict = null;          // { id, chamber } when user clicks a district

  // Escape key — unlock sidebar (module-level, not inside attachMouseHandlers)
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && lockedDistrict) {
      lockedDistrict = null;
      hideTooltip();
    }
  });

  // ── Mapbox init ──────────────────────────────────────────────────────────────
  if (!FDGA.token) {
    console.error('FDGA: No Mapbox token found. Set window.MAPBOX_TOKEN before map.js loads.');
    document.getElementById('map').innerHTML =
      '<div style="padding:2rem;color:#c00">Mapbox token missing — check server config.</div>';
    return;
  }

  mapboxgl.accessToken = FDGA.token;

  const isMobile = window.matchMedia('(max-width: 785px)').matches;

  const map = new mapboxgl.Map({
    container: 'map',
    style: 'mapbox://styles/mapbox/light-v11',
    center: [-83.208092, 32.482618],
    zoom: isMobile ? 5 : 6.5,
    maxZoom: 13,
    minZoom: 4,
  });

  // Geocoder
  map.addControl(new MapboxGeocoder({
    accessToken: mapboxgl.accessToken,
    bbox: [-86.548059, 30.183318, -80.840278, 35.451994],
    mapboxgl: mapboxgl,
    marker: true,
    placeholder: 'Search for an address…',
  }), 'top-right');

  map.addControl(new mapboxgl.NavigationControl(), 'top-right');

  // ── Build sources & layers from config ───────────────────────────────────────
  map.on('load', () => {
    // Boundary sources
    map.addSource('src_counties', FDGA.BOUNDARY_SOURCES.counties);
    map.addSource('src_cities',   FDGA.BOUNDARY_SOURCES.cities);

    // County & city layers
    map.addLayer({
      id: 'county_borders', type: 'line', source: 'src_counties',
      layout: { visibility: 'none' },
      paint: { 'line-color': '#888', 'line-width': 1 }
    });
    map.addLayer({
      id: 'city_borders', type: 'line', source: 'src_cities',
      layout: { visibility: 'none' },
      paint: { 'line-color': '#0AB2BB', 'line-width': 1.5 }
    });

    // District sources and layers — generated from config
    FDGA.DISTRICT_MAPS.forEach(dm => {
      // Source
      map.addSource(`src_${dm.id}`, {
        type: 'geojson',
        data: `/data/${dm.file}`,
      });

      // Outline layer (always visible when this map is selected)
      map.addLayer({
        id: dm.id,
        type: 'line',
        source: `src_${dm.id}`,
        layout: { visibility: 'none' },
        paint: { 'line-color': '#444', 'line-width': 1.5 }
      });

      // Fill layer (shown when demographic overlay is active)
      map.addLayer({
        id: `${dm.id}_fill`,
        type: 'fill',
        source: `src_${dm.id}`,
        layout: { visibility: 'none' },
        paint: { 'fill-opacity': 0.75, 'fill-color': '#ccc' }
      });

      // Hover highlight layer
      map.addLayer({
        id: `${dm.id}_hover`,
        type: 'line',
        source: `src_${dm.id}`,
        layout: { visibility: 'none' },
        paint: { 'line-color': '#c90000', 'line-width': 3 },
        filter: ['==', 'DISTRICT', ''],
      });

      // Transparent interaction layer (catches mouse events)
      map.addLayer({
        id: `${dm.id}_popup`,
        type: 'fill',
        source: `src_${dm.id}`,
        layout: { visibility: 'none' },
        paint: { 'fill-opacity': 0 }
      });
    });

    // Attach mouse handlers to all popup layers
    attachMouseHandlers();

    // Set initial state from URL params (shareable links) or dropdown defaults
    readUrlState();
    handleLevelChange();
    handleMeasureChange();
  });

  // ── Mouse handlers (single pair, not 18 copies) ───────────────────────────
  function attachMouseHandlers() {
    map.on('mousemove', (e) => {
      // Find which popup layer we're over
      const hit = map.queryRenderedFeatures(e.point, { layers: POPUP_LAYER_IDS });
      if (!hit.length) return;

      const feature = hit[0];
      const mapId   = feature.layer.id.replace('_popup', '');
      const props   = feature.properties;

      // Hover highlight — use DISTRICT (uppercase, matches GeoJSON)
      const districtVal = props.DISTRICT || props.district || '';
      map.setFilter(`${mapId}_hover`, ['==', 'DISTRICT', String(districtVal)]);
      map.setLayoutProperty(`${mapId}_hover`, 'visibility', 'visible');
      map.getCanvas().style.cursor = 'pointer';

      // Only update hover tooltip when not locked on a district
      if (!lockedDistrict) showTooltip(props, mapId);
    });

    map.on('mouseleave', (e) => {
      // Clear all hover filters
      FDGA.DISTRICT_MAPS.forEach(dm => {
        if (map.getLayer(`${dm.id}_hover`)) {
          map.setFilter(`${dm.id}_hover`, ['==', 'DISTRICT', '']);
          map.setLayoutProperty(`${dm.id}_hover`, 'visibility', 'none');
        }
      });
      map.getCanvas().style.cursor = '';
      if (!lockedDistrict) hideTooltip();
    });

    // Single click handler — locks sidebar on district hit, unlocks on empty click
    map.on('click', (e) => {
      const hit = map.queryRenderedFeatures(e.point, { layers: POPUP_LAYER_IDS });
      if (hit.length) {
        const mapId  = hit[0].layer.id.replace('_popup', '');
        const props  = hit[0].properties;
        const dm     = FDGA.DISTRICT_MAPS.find(d => d.id === mapId);
        const districtId = parseInt(props.DISTRICT || props.district);
        lockedDistrict = { id: districtId, chamber: dm ? dm.chamber : null };
        showTooltip(props, mapId, true);
      } else if (lockedDistrict) {
        lockedDistrict = null;
        hideTooltip();
      }
    });
  }

  // ── Tooltip / Sidebar ──────────────────────────────────────────────────────
  function showTooltip(props, mapId, locked = false) {
    const dm = FDGA.DISTRICT_MAPS.find(d => d.id === mapId);
    const mapLabel = dm ? dm.label : mapId;
    const chamber  = dm ? dm.chamber : null;

    const district = props.DISTRICT || props.district || '—';
    const districtId = parseInt(district);

    // Helper: format a 0–1 value as percent, handle missing
    const pct = (v) => (v != null && v !== '') ? (parseFloat(v) * 100).toFixed(1) + '%' : '—';
    const num = (v) => (v != null && v !== '') ? parseInt(v).toLocaleString('en-US') : '—';

    const sidebar = document.getElementById('sidebar');
    sidebar.style.display = 'block';
    sidebar.classList.toggle('locked', locked);

    const lockHint = locked
      ? '<div class="tt-lock-hint">Press <kbd>Esc</kbd> to close</div>'
      : '';

    // Show "View AI Analysis" button only for enacted_2024 maps with valid district IDs
    const supportsNarrative = dm && dm.version === 'enacted_2024' && !isNaN(districtId);

    document.getElementById('tooltip-content').innerHTML = `
      ${lockHint}
      <div class="tt-header">${mapLabel}</div>
      <div class="tt-district">District ${district}</div>
      <table class="tt-table">
        <tr><td>Total Population</td><td>${num(props.pop || props.TOT_POP)}</td></tr>
        <tr><td>Voting Age Pop.</td><td>${num(props.tvap || props.VAP)}</td></tr>
        <tr><td>Black VAP</td><td>${pct(props.pct_bvp)}</td></tr>
        <tr><td>Hispanic VAP</td><td>${pct(props.pct_hvp)}</td></tr>
        <tr><td>Asian VAP</td><td>${pct(props.pct_avp)}</td></tr>
        <tr><td>Minority VAP</td><td>${pct(props.pct_bp_)}</td></tr>
        <tr><td>Partisan Lean (Dem)</td><td>${pct(props.partisan)}</td></tr>
      </table>
      ${locked && supportsNarrative ? '<button class="narrative-btn">View AI Analysis</button>' : ''}
    `;

    // Attach narrative button event after DOM is updated — no inline onclick
    if (locked && supportsNarrative) {
      const btn = document.querySelector('#tooltip-content .narrative-btn');
      if (btn) btn.addEventListener('click', () => loadNarrative(chamber, districtId, btn));
    }
  }

  function hideTooltip() {
    const sidebar = document.getElementById('sidebar');
    sidebar.style.display = 'none';
    sidebar.classList.remove('locked');
    document.getElementById('tooltip-content').innerHTML = '';
  }

  // ── AI Narrative fetch (persistent floating panel) ────────────────────────
  const _narrativeCache = {};  // key: `${chamber}-${districtId}`

  function showNarrativePanel(title, bodyHtml) {
    document.getElementById('narrative-panel-title').textContent = title;
    document.getElementById('narrative-panel-body').innerHTML    = bodyHtml;
    document.getElementById('narrative-panel').classList.remove('hidden');
  }

  document.getElementById('narrative-panel-close').addEventListener('click', () => {
    document.getElementById('narrative-panel').classList.add('hidden');
  });

  function loadNarrative(chamber, districtId, btn) {
    const cacheKey = `${chamber}-${districtId}`;
    const title    = `${chamber.charAt(0).toUpperCase() + chamber.slice(1)} District ${districtId}`;

    // If already cached, show immediately
    if (_narrativeCache[cacheKey]) {
      showNarrativePanel(title, _narrativeCache[cacheKey]);
      btn.textContent = 'View Analysis';
      btn.disabled    = false;
      return;
    }

    // Show panel with loading skeleton immediately — user can navigate away
    btn.disabled    = true;
    btn.textContent = 'Generating…';
    showNarrativePanel(title,
      '<div class="narrative-loading"><div></div><div></div><div></div></div>' +
      '<div style="font-size:0.72rem;color:#999;margin-top:8px">Generating analysis — this may take up to a minute…</div>'
    );

    fetch(`/api/districts/${chamber}/${districtId}/narrative`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        const html = `<div class="narrative-text">${escapeHtml(data.narrative || 'No narrative available.')}</div>`;
        _narrativeCache[cacheKey] = html;
        // Update panel (stays open even if user moved away)
        showNarrativePanel(title, html);
        // Re-enable the button in the sidebar if still on screen
        const sidebarBtn = document.querySelector('#tooltip-content .narrative-btn');
        if (sidebarBtn) { sidebarBtn.textContent = 'View Analysis'; sidebarBtn.disabled = false; }
      })
      .catch(() => {
        const errHtml = '<div class="narrative-error">Could not load — check that the AI service is running.</div>';
        _narrativeCache[cacheKey] = null;  // allow retry
        showNarrativePanel(title, errHtml);
        const sidebarBtn = document.querySelector('#tooltip-content .narrative-btn');
        if (sidebarBtn) { sidebarBtn.textContent = 'Retry Analysis'; sidebarBtn.disabled = false; }
      });
  }

  function escapeHtml(str) {
    return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  // ── Layer visibility helpers ──────────────────────────────────────────────
  function hideAllDistrictLayers() {
    FDGA.DISTRICT_MAPS.forEach(dm => {
      ['', '_fill', '_hover', '_popup'].forEach(suffix => {
        const id = `${dm.id}${suffix}`;
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', 'none');
      });
    });
  }

  function showDistrictLayers(mapId, withFill) {
    if (!map.getLayer(mapId)) return;
    map.setLayoutProperty(mapId, 'visibility', 'visible');
    map.setLayoutProperty(`${mapId}_popup`, 'visibility', 'visible');
    if (withFill && map.getLayer(`${mapId}_fill`)) {
      map.setLayoutProperty(`${mapId}_fill`, 'visibility', 'visible');
    }
  }

  // ── Demographic fill color ────────────────────────────────────────────────
  function applyFillColors(mapId, measure) {
    if (!measure || !FDGA.COLORS[measure]) return;
    const fillLayerId = `${mapId}_fill`;
    if (!map.getLayer(fillLayerId)) return;

    const stops = FDGA.COLORS[measure];
    const prop  = FDGA.DEMOGRAPHICS[measure].prop;

    map.setPaintProperty(fillLayerId, 'fill-color', {
      property: prop,
      type: 'interval',
      stops: stops.map(([val, color]) => [val, color]),
      default: '#d4d5d5',
    });
  }

  // ── Legend ────────────────────────────────────────────────────────────────
  function updateLegend(measure) {
    const container = document.getElementById('legend-container');
    const titleEl   = document.getElementById('legend-title');
    const swatchEl  = document.getElementById('legend-swatches');

    if (!measure || !FDGA.COLORS[measure]) {
      container.style.display = 'none';
      return;
    }

    const demo   = FDGA.DEMOGRAPHICS[measure];
    const colors = FDGA.COLORS[measure].slice(0, -1); // drop the grey no-data stop
    const labels = FDGA.LEGEND_LABELS[measure] || [];

    titleEl.textContent = demo.label;
    swatchEl.innerHTML = colors.map((([, color], i) => `
      <div class="legend-row">
        <span class="legend-swatch" style="background:${color}"></span>
        <span class="legend-label">${labels[i] || ''}</span>
      </div>
    `)).join('');

    container.style.display = 'block';
  }

  // ── URL state sync (shareable links) ─────────────────────────────────────
  function readUrlState() {
    const p = new URLSearchParams(window.location.search);
    const mapParam     = p.get('map');
    const overlayParam = p.get('overlay');
    if (mapParam && FDGA.DISTRICT_MAPS.some(d => d.id === mapParam)) {
      currentMapId = mapParam;
      document.getElementById('level').value = mapParam;
    }
    if (overlayParam !== null) {
      currentMeasure = overlayParam;
      document.getElementById('measure').value = overlayParam;
    }
  }

  function pushUrlState() {
    const p = new URLSearchParams();
    if (currentMapId   !== DEFAULT_MAP_ID) p.set('map',     currentMapId);
    if (currentMeasure !== '')             p.set('overlay', currentMeasure);
    const qs = p.toString();
    history.replaceState(null, '', qs ? '?' + qs : window.location.pathname);
  }

  // ── Control handlers ──────────────────────────────────────────────────────
  function handleLevelChange() {
    const sel = document.getElementById('level');
    currentMapId = sel.value;
    if (!currentMapId) return;

    // Clear locked district when switching maps
    lockedDistrict = null;
    hideTooltip();

    hideAllDistrictLayers();
    showDistrictLayers(currentMapId, showFill);

    if (showFill && currentMeasure) {
      applyFillColors(currentMapId, currentMeasure);
    }
    pushUrlState();
  }

  function handleMeasureChange() {
    const sel = document.getElementById('measure');
    currentMeasure = sel.value;

    updateLegend(currentMeasure);

    if (showFill && currentMapId && currentMeasure) {
      applyFillColors(currentMapId, currentMeasure);
    }
    pushUrlState();
  }

  function handleFillToggle() {
    showFill = document.getElementById('show_district').checked;
    if (!currentMapId) return;

    if (showFill) {
      map.setLayoutProperty(`${currentMapId}_fill`, 'visibility', 'visible');
      if (currentMeasure) applyFillColors(currentMapId, currentMeasure);
    } else {
      map.setLayoutProperty(`${currentMapId}_fill`, 'visibility', 'none');
    }
  }

  function handleCountyToggle() {
    showCounty = document.getElementById('show_county').checked;
    map.setLayoutProperty('county_borders', 'visibility', showCounty ? 'visible' : 'none');
  }

  function handleCityToggle() {
    showCity = document.getElementById('show_city').checked;
    map.setLayoutProperty('city_borders', 'visibility', showCity ? 'visible' : 'none');
  }

  // ── Wire up controls ──────────────────────────────────────────────────────
  document.getElementById('level').addEventListener('change', handleLevelChange);
  document.getElementById('measure').addEventListener('change', handleMeasureChange);
  document.getElementById('show_district').addEventListener('change', handleFillToggle);
  document.getElementById('show_county').addEventListener('change', handleCountyToggle);
  document.getElementById('show_city').addEventListener('change', handleCityToggle);

  // ── District locate ──────────────────────────────────────────────────────
  const _geoCache = {};

  async function locateByDistrict(query) {
    const num = parseInt(query, 10);
    if (isNaN(num) || !currentMapId) return;

    if (!_geoCache[currentMapId]) {
      const dm = FDGA.DISTRICT_MAPS.find(d => d.id === currentMapId);
      if (!dm) return;
      try {
        const resp = await fetch(`/data/${dm.file}`);
        const gj   = await resp.json();
        _geoCache[currentMapId] = gj.features;
      } catch (e) { return; }
    }

    const feat = _geoCache[currentMapId].find(f =>
      parseInt(f.properties.DISTRICT || f.properties.district, 10) === num
    );
    if (!feat) return;

    const coords = feat.geometry.type === 'MultiPolygon'
      ? feat.geometry.coordinates.flatMap(p => p.flatMap(r => r))
      : feat.geometry.coordinates.flatMap(r => r);
    const lngs = coords.map(c => c[0]);
    const lats  = coords.map(c => c[1]);
    map.fitBounds(
      [[Math.min(...lngs), Math.min(...lats)], [Math.max(...lngs), Math.max(...lats)]],
      { padding: 60, duration: 600 }
    );
  }

  const locateInput = document.getElementById('map-locate-input');
  if (locateInput) {
    locateInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        locateByDistrict(locateInput.value.trim());
        locateInput.blur();
      }
    });
  }

  // Expose map for chat.js to access current context
  window.FDGA.map        = map;
  window.FDGA.getContext = () => ({
    mapId:   currentMapId,
    measure: currentMeasure,
    label:   (FDGA.DISTRICT_MAPS.find(d => d.id === currentMapId) || {}).label || currentMapId,
    version: (FDGA.DISTRICT_MAPS.find(d => d.id === currentMapId) || {}).version || '',
  });

})();
