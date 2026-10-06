import { ASTraMCampusViewer } from './three_campus_loader.js';

const API_BASE = window.ASTRAM_API_BASE || window.location.origin;
const MAP_CENTER = [18.5182, 73.8180];
const MAP_ZOOM = 17;
const ROAD_COLORS = Object.freeze({ free: '#22c55e', moderate: '#eab308', warning: '#f97316', severe: '#ef4444' });
const PHASE_NAMES = Object.freeze({
  north_approach: 'North approach',
  east_approach: 'East approach',
  south_approach: 'South approach',
  west_approach: 'West approach',
});
const state = {
  map: null,
  roadLayer: null,
  network: null,
  edgeMetrics: new Map(),
  activeSignalPhases: {},
  signalTiming: null,
  ws: null,
  reconnectDelay: 1000,
  reconnectTimer: null,
  mapMatchEnabled: false,
  mapMarker: null,
  vehicleMarkers: new Map(),
  viewer: null,
  currentView: '2d',
  lastSnapshotAt: null,
  solveBusy: false,
  gpsBusy: false,
};

const $ = (id) => document.getElementById(id);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function setConnection(stateName, label) {
  const pill = $('connection-status');
  pill.dataset.state = stateName;
  $('connection-label').textContent = label;
}

function setOverlayError(message) {
  const error = $('map-error');
  error.textContent = message;
  error.classList.remove('is-hidden');
}

function clearOverlayError() {
  $('map-error').classList.add('is-hidden');
}

function saturationColor(ratio) {
  const rho = Number(ratio);
  if (!Number.isFinite(rho) || rho < 0.5) return ROAD_COLORS.free;
  if (rho < 0.75) return ROAD_COLORS.moderate;
  if (rho < 0.9) return ROAD_COLORS.warning;
  return ROAD_COLORS.severe;
}

function getEdgeMetric(edgeId) {
  return state.edgeMetrics.get(String(edgeId)) || {};
}

function updateEdgeMetric(edgeId, incoming) {
  const id = String(edgeId);
  const prior = state.edgeMetrics.get(id) || {};
  state.edgeMetrics.set(id, { ...prior, ...incoming });
}

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  });
  let data;
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    const detail = typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`;
    throw new Error(detail);
  }
  return data;
}

function initMap() {
  if (!window.L) throw new Error('Leaflet failed to load. Check the browser connection to its CDN.');
  state.map = L.map('campus-map', { zoomControl: true, preferCanvas: true }).setView(MAP_CENTER, MAP_ZOOM);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 21,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  }).addTo(state.map);
  state.roadLayer = L.geoJSON(null, {
    style: (feature) => roadStyle(feature),
    onEachFeature: (feature, layer) => bindRoadPopup(feature, layer),
  }).addTo(state.map);
  state.map.on('click', (event) => {
    if (state.mapMatchEnabled) requestMapMatchAt(event.latlng.lat, event.latlng.lng);
  });
}

function roadStyle(feature) {
  const props = feature?.properties || {};
  const metric = getEdgeMetric(props.id);
  const saturation = metric.saturation_ratio ?? props.saturation_ratio ?? 0;
  return {
    color: saturationColor(saturation),
    weight: 5,
    opacity: 0.9,
    lineCap: 'round',
    lineJoin: 'round',
  };
}

function bindRoadPopup(feature, layer) {
  const props = feature?.properties || {};
  layer.on('click', () => {
    const metric = getEdgeMetric(props.id);
    const number = (value, digits = 1) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
    const content = `<div class="edge-popup">
      <strong>${escapeHtml(props.name || 'Campus road segment')} <span class="edge-id">${escapeHtml(props.id || '')}</span></strong>
      <div class="edge-popup-grid">
        <span>Flow</span><b>${number(metric.flow ?? props.real_time_flow)} veh/hr</b>
        <span>Capacity</span><b>${number(props.capacity, 0)} veh/hr</b>
        <span>Saturation</span><b>${number((metric.saturation_ratio ?? props.saturation_ratio) * 100, 1)}%</b>
        <span>BPR delay</span><b>${number(metric.delay_sec ?? props.delay_sec)} sec</b>
        <span>Effective speed</span><b>${number(metric.effective_speed_kmh ?? props.effective_speed_kmh)} km/h</b>
      </div>
    </div>`;
    layer.bindPopup(content, { maxWidth: 270 }).openPopup();
  });
}

async function loadNetwork() {
  try {
    const network = await apiRequest('/api/v1/network', { method: 'GET', headers: {} });
    state.network = network;
    for (const feature of network.features || []) {
      const props = feature.properties || {};
      updateEdgeMetric(props.id, {
        flow: props.real_time_flow,
        saturation_ratio: props.saturation_ratio,
        travel_time_sec: props.travel_time_sec,
        delay_sec: props.delay_sec,
        effective_speed_kmh: props.effective_speed_kmh,
        capacity: props.capacity,
        name: props.name,
      });
    }
    state.roadLayer.clearLayers();
    state.roadLayer.addData(network);
    const bounds = state.roadLayer.getBounds();
    if (bounds.isValid()) state.map.fitBounds(bounds.pad(0.16), { maxZoom: 18 });
    $('map-layer-count').textContent = `${network.features.length} directed links`;
    $('map-loading').classList.add('is-hidden');
    updateMapColors();
    renderLiveMetrics();
  } catch (error) {
    $('map-loading').classList.add('is-hidden');
    setOverlayError(`Could not load campus road data: ${error.message}`);
  }
}

function updateMapColors() {
  if (state.roadLayer) state.roadLayer.setStyle((feature) => roadStyle(feature));
  if (state.viewer) {
    const saturationData = Object.fromEntries(
      [...state.edgeMetrics.entries()].map(([edgeId, metric]) => [edgeId, metric.saturation_ratio ?? 0]),
    );
    state.viewer.update3DRoadColors(saturationData);
  }
}

function updateLiveEdges(edges) {
  if (!Array.isArray(edges)) return;
  for (const edge of edges) {
    if (typeof edge.edge_id !== 'string') continue;
    updateEdgeMetric(edge.edge_id, {
      flow: edge.flow,
      saturation_ratio: edge.saturation_ratio,
      travel_time_sec: edge.travel_time_sec,
      delay_sec: edge.delay_sec,
      effective_speed_kmh: edge.effective_speed_kmh,
      capacity_warning: edge.capacity_warning,
    });
  }
  updateMapColors();
  renderLiveMetrics();
  renderAlertFeed();
}

function renderLiveMetrics() {
  const metrics = [...state.edgeMetrics.values()];
  if (!metrics.length) return;
  const validSaturation = metrics.map((item) => Number(item.saturation_ratio)).filter(Number.isFinite);
  const validFlows = metrics.map((item) => Number(item.flow)).filter(Number.isFinite);
  const averageSaturation = validSaturation.length
    ? validSaturation.reduce((sum, value) => sum + value, 0) / validSaturation.length
    : 0;
  const averageLinkFlow = validFlows.length
    ? validFlows.reduce((sum, value) => sum + value, 0) / validFlows.length
    : 0;
  const warningCount = validSaturation.filter((value) => value >= 0.75).length;
  $('total-flow').textContent = Math.round(averageLinkFlow).toLocaleString();
  $('average-saturation').textContent = (averageSaturation * 100).toFixed(1);
  $('warning-count').textContent = warningCount.toLocaleString();
  $('warning-summary').textContent = warningCount ? 'Preemptive action recommended' : '75% buffer threshold';
  $('alert-count-badge').textContent = String(warningCount);
  $('alert-count-badge').classList.toggle('has-alerts', warningCount > 0);
  $('flow-snapshot').textContent = `${validFlows.length} road links reporting`;
}

function renderAlertFeed() {
  const warnings = [...state.edgeMetrics.entries()]
    .map(([edgeId, metric]) => ({ edgeId, ...metric, rho: Number(metric.saturation_ratio) }))
    .filter((item) => Number.isFinite(item.rho) && item.rho >= 0.75)
    .sort((a, b) => b.rho - a.rho);
  const feed = $('alert-feed');
  if (!warnings.length) {
    feed.innerHTML = '<div class="alert-empty"><span>✓</span><p>No links above the 75% capacity buffer.</p></div>';
    return;
  }
  feed.replaceChildren(...warnings.slice(0, 8).map((item) => {
    const card = document.createElement('div');
    card.className = `alert-item${item.rho >= 0.9 ? ' severe' : ''}`;
    const title = document.createElement('div');
    title.className = 'alert-title';
    title.textContent = `${item.name || item.edgeId} · ${item.edgeId}`;
    const detail = document.createElement('div');
    detail.className = 'alert-detail';
    detail.textContent = item.rho >= 0.9 ? 'Severe gridlock threshold reached' : 'Approaching physical capacity';
    const badge = document.createElement('span');
    badge.className = 'alert-badge';
    badge.textContent = `${(item.rho * 100).toFixed(1)}%`;
    card.append(title, detail, badge);
    return card;
  }));
}

function renderSignalTiming(timing) {
  if (!timing) return;
  state.signalTiming = timing;
  $('cycle-value').textContent = Number(timing.cycle_time_sec || 0).toFixed(0);
  $('cycle-total').textContent = Number(timing.cycle_time_sec || 0).toFixed(0);
  $('amber-value').textContent = Number(timing.amber_clearance_sec || 0).toFixed(0);
  const greens = timing.green_phase_durations_sec || timing.green_times_sec || {};
  const maxGreen = Math.max(1, ...Object.values(greens).map(Number));
  const phaseNames = Object.keys(greens);
  const container = $('signal-phases');
  if (!phaseNames.length) return;
  container.replaceChildren(...phaseNames.map((name) => {
    const card = document.createElement('div');
    const stateName = state.activeSignalPhases[name];
    card.className = `signal-phase${stateName === 'green' ? ' is-green' : ''}`;
    card.dataset.phase = name;
    const top = document.createElement('div');
    top.className = 'signal-phase-top';
    const title = document.createElement('span');
    title.className = 'signal-phase-name';
    title.textContent = PHASE_NAMES[name] || name.replaceAll('_', ' ');
    const light = document.createElement('i');
    light.className = 'signal-light';
    light.setAttribute('aria-label', stateName || 'inactive');
    top.append(title, light);
    const seconds = document.createElement('p');
    seconds.className = 'signal-seconds';
    seconds.append(document.createTextNode(Number(greens[name]).toFixed(1)));
    const unit = document.createElement('small');
    unit.textContent = 'sec green';
    seconds.append(unit);
    const track = document.createElement('div');
    track.className = 'signal-track';
    const fill = document.createElement('i');
    fill.style.width = `${Math.max(0, Math.min(100, Number(greens[name]) / maxGreen * 100))}%`;
    track.append(fill);
    card.append(top, seconds, track);
    return card;
  }));
  updateSignalLights();
}

function updateSignalLights() {
  document.querySelectorAll('.signal-phase').forEach((card) => {
    const phaseState = state.activeSignalPhases[card.dataset.phase];
    card.classList.toggle('is-green', phaseState === 'green');
    card.classList.toggle('is-amber', phaseState === 'amber');
    const light = card.querySelector('.signal-light');
    if (light) light.setAttribute('aria-label', phaseState || 'inactive');
  });
}

function setView(view) {
  state.currentView = view;
  const is3d = view === '3d';
  $('campus-map').classList.toggle('is-visible', !is3d);
  $('campus-3d').classList.toggle('is-visible', is3d);
  $('view-2d-button').classList.toggle('is-active', !is3d);
  $('view-3d-button').classList.toggle('is-active', is3d);
  $('view-2d-button').setAttribute('aria-pressed', String(!is3d));
  $('view-3d-button').setAttribute('aria-pressed', String(is3d));
  $('map-heading').textContent = is3d ? 'MIT-WPU 3D campus' : 'MIT-WPU live map';
  if (is3d) {
    ensure3DViewer();
    requestAnimationFrame(() => state.viewer?.resize());
  } else {
    requestAnimationFrame(() => state.map?.invalidateSize(false));
  }
}

function ensure3DViewer() {
  if (state.viewer) return;
  try {
    state.viewer = new ASTraMCampusViewer({
      container: $('campus-3d'),
      assetUrl: '/static/assets/mit_wpu_campus.glb',
      connectWebSocket: false,
      onError: (error) => setOverlayError(`3D campus asset unavailable: ${error.message}`),
    });
    state.viewer.ready.then(() => {
      clearOverlayError();
      updateMapColors();
      state.viewer.resize();
    }).catch(() => {});
  } catch (error) {
    setOverlayError(`3D viewer could not start: ${error.message}`);
  }
}

function setMatchMode(enabled) {
  state.mapMatchEnabled = enabled;
  const button = $('map-match-mode');
  button.setAttribute('aria-pressed', String(enabled));
  button.textContent = enabled ? '× Stop map snap testing' : '⌖ Click map to test GPS snap';
  $('campus-map').style.cursor = enabled ? 'crosshair' : '';
}

async function requestMapMatchAt(latitude, longitude) {
  $('gps-latitude').value = Number(latitude).toFixed(6);
  $('gps-longitude').value = Number(longitude).toFixed(6);
  await submitGPSFix(latitude, longitude);
}

async function submitGPSFix(latitude = Number($('gps-latitude').value), longitude = Number($('gps-longitude').value)) {
  if (state.gpsBusy) return;
  state.gpsBusy = true;
  $('gps-error').classList.add('is-hidden');
  $('gps-submit').disabled = true;
  $('gps-submit').textContent = 'Matching location…';
  try {
    const headingValue = $('gps-heading').value;
    const speedKmh = Number($('gps-speed').value);
    const payload = {
      device_id: $('gps-device').value.trim() || 'dashboard-simulator',
      latitude: Number(latitude),
      longitude: Number(longitude),
      heading: headingValue === '' ? null : Number(headingValue),
      speed: Number.isFinite(speedKmh) ? speedKmh / 3.6 : null,
    };
    const result = await apiRequest('/api/v1/map-match', { method: 'POST', body: JSON.stringify(payload) });
    renderGPSResult(result);
  } catch (error) {
    $('gps-error').textContent = error.message;
    $('gps-error').classList.remove('is-hidden');
  } finally {
    state.gpsBusy = false;
    $('gps-submit').disabled = false;
    $('gps-submit').textContent = 'Test snap to road';
  }
}

function renderGPSResult(result) {
  $('gps-result').classList.remove('is-hidden');
  const badge = $('gps-network-badge');
  badge.textContent = result.is_on_network ? 'ON NETWORK' : 'OFF ROAD';
  badge.classList.toggle('is-on', result.is_on_network);
  badge.classList.toggle('is-off', !result.is_on_network);
  $('gps-road-name').textContent = result.is_on_network
    ? `${result.matched_edge_name} · ${result.matched_edge_id}`
    : 'Off-Road / Pedestrian Path';
  $('gps-distance').textContent = result.cross_track_distance_m == null
    ? '—'
    : `${Number(result.cross_track_distance_m).toFixed(2)} m`;
  $('gps-heading-delta').textContent = result.heading_delta_deg == null
    ? '—'
    : `${Number(result.heading_delta_deg).toFixed(1)}°`;
  $('gps-confidence').textContent = `${(Number(result.confidence_score) * 100).toFixed(0)}%`;
  if (state.mapMarker) state.map.removeLayer(state.mapMarker);
  const position = result.is_on_network
    ? [result.snapped_latitude, result.snapped_longitude]
    : [Number($('gps-latitude').value), Number($('gps-longitude').value)];
  state.mapMarker = L.circleMarker(position, {
    radius: 7,
    color: result.is_on_network ? '#38bdf8' : '#f97316',
    weight: 2,
    fillColor: result.is_on_network ? '#0ea5e9' : '#fb923c',
    fillOpacity: 0.9,
  }).addTo(state.map).bindTooltip(result.is_on_network ? 'Snapped GPS fix' : 'Off-road GPS fix');
}

function currentScenario() {
  const gate1 = Number($('gate1-number').value);
  const paud = Number($('paud-number').value);
  const exitVolume = Number($('exit-number').value);
  return { gate1, paud, exitVolume };
}

function setInputPair(prefix, value) {
  $(`${prefix}-range`).value = String(value);
  $(`${prefix}-number`).value = String(value);
  $(`${prefix}-output`).textContent = String(value);
}

function updateScenarioControls(changed) {
  let { gate1, paud, exitVolume } = currentScenario();
  if (![gate1, paud, exitVolume].every(Number.isFinite)) return;
  gate1 = Math.max(0, Math.min(150, Math.round(gate1)));
  paud = Math.max(-140, Math.min(140, Math.round(paud)));
  exitVolume = Math.max(0, Math.min(70, Math.round(exitVolume)));
  if (changed === 'exit') {
    paud = exitVolume - gate1;
    paud = Math.max(-140, Math.min(140, paud));
    exitVolume = gate1 + paud;
  } else {
    exitVolume = gate1 + paud;
  }
  setInputPair('gate1', gate1);
  setInputPair('paud', paud);
  setInputPair('exit', exitVolume);
  const balanced = gate1 + paud - exitVolume === 0;
  const withinCapacity = exitVolume >= 0 && exitVolume <= 70;
  const valid = balanced && withinCapacity;
  $('scenario-validation').classList.toggle('is-invalid', !valid);
  $('scenario-validation').textContent = valid
    ? `Boundary flows balance. Exit capacity: 70 veh/hr.`
    : `Scenario exceeds modeled West Parking exit capacity (70 veh/hr). Adjust Gate 1 or Paud flow.`;
  $('solve-flow-button').disabled = !valid || state.solveBusy;
}

async function solveScenario() {
  const { gate1, paud, exitVolume } = currentScenario();
  if (gate1 + paud !== exitVolume || exitVolume > 70 || exitVolume < 0) return;
  state.solveBusy = true;
  $('solve-flow-button').disabled = true;
  $('solve-flow-button').innerHTML = '<span>⟳</span> Solving network…';
  $('solve-error').classList.add('is-hidden');
  try {
    const result = await apiRequest('/api/v1/solve-flow', {
      method: 'POST',
      body: JSON.stringify({ node_1: gate1, node_7: paud, node_8: -exitVolume }),
    });
    for (const [edgeId, flow] of Object.entries(result.X || {})) {
      updateEdgeMetric(edgeId, {
        flow,
        saturation_ratio: result.saturation_ratios?.[edgeId],
        delay_sec: result.bpr_delay_penalties_sec?.[edgeId],
        effective_speed_kmh: result.effective_speeds_kmh?.[edgeId],
        travel_time_sec: result.travel_times_sec?.[edgeId],
      });
    }
    renderSignalTiming(result.signal_timing);
    updateMapColors();
    renderLiveMetrics();
    renderAlertFeed();
    $('flow-snapshot').textContent = `Residual ${Number(result.residual_error).toExponential(1)}`;
    $('last-update').textContent = `Scenario solved ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    $('solve-error').textContent = error.message;
    $('solve-error').classList.remove('is-hidden');
  } finally {
    state.solveBusy = false;
    $('solve-flow-button').innerHTML = '<span>⟳</span> Recalculate traffic flow';
    updateScenarioControls(null);
  }
}

function updateFromTrafficState(packet) {
  if (!packet || typeof packet !== 'object') return;
  updateLiveEdges(packet.edges);
  if (packet.active_signal_phases && typeof packet.active_signal_phases === 'object') {
    state.activeSignalPhases = packet.active_signal_phases;
    if (packet.signal_timing && Object.keys(packet.signal_timing).length) {
      renderSignalTiming(packet.signal_timing);
    }
    updateSignalLights();
  }
  if (Number.isFinite(Number(packet.simulation_tick))) {
    $('simulation-tick').textContent = `Simulation tick ${packet.simulation_tick}`;
  }
  if (Array.isArray(packet.vehicle_positions)) {
    updateVehicleMarkers(packet.vehicle_positions);
    $('flow-snapshot').title = `${packet.vehicle_positions.length} simulated vehicle positions in stream`;
  }
  state.lastSnapshotAt = new Date();
  $('last-update').textContent = `Live update ${state.lastSnapshotAt.toLocaleTimeString()}`;
  if (state.viewer) {
    state.viewer.update3DRoadColors({ edges: packet.edges || [] });
  }
}

function updateVehicleMarkers(vehicles) {
  if (!state.map || !window.L) return;
  const activeIds = new Set();
  for (const vehicle of vehicles) {
    if (typeof vehicle.vehicle_id !== 'string' || !Number.isFinite(Number(vehicle.latitude)) || !Number.isFinite(Number(vehicle.longitude))) continue;
    activeIds.add(vehicle.vehicle_id);
    const position = [Number(vehicle.latitude), Number(vehicle.longitude)];
    let marker = state.vehicleMarkers.get(vehicle.vehicle_id);
    if (!marker) {
      marker = L.circleMarker(position, {
        radius: 5,
        color: '#e0f2fe',
        weight: 1.5,
        fillColor: '#38bdf8',
        fillOpacity: 1,
        pane: 'markerPane',
      }).addTo(state.map);
      marker.bindTooltip(`Simulated vehicle · ${escapeHtml(vehicle.edge_id || '')}`);
      state.vehicleMarkers.set(vehicle.vehicle_id, marker);
    } else {
      marker.setLatLng(position);
      marker.setTooltipContent(`Simulated vehicle · ${escapeHtml(vehicle.edge_id || '')}`);
    }
    marker.setStyle({ fillColor: '#38bdf8' });
  }
  for (const [vehicleId, marker] of state.vehicleMarkers) {
    if (!activeIds.has(vehicleId)) {
      state.map.removeLayer(marker);
      state.vehicleMarkers.delete(vehicleId);
    }
  }
}

function connectWebSocket() {
  if (state.ws && [WebSocket.OPEN, WebSocket.CONNECTING].includes(state.ws.readyState)) return;
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const socket = new WebSocket(`${protocol}//${window.location.host}/ws/traffic-stream`);
  state.ws = socket;
  setConnection('connecting', 'CONNECTING');
  socket.addEventListener('open', () => {
    state.reconnectDelay = 1000;
    setConnection('online', 'ONLINE / STREAMING');
  });
  socket.addEventListener('message', (event) => {
    try {
      updateFromTrafficState(JSON.parse(event.data));
    } catch (error) {
      console.error('Could not process ASTraM traffic stream packet', error);
    }
  });
  socket.addEventListener('error', () => socket.close());
  socket.addEventListener('close', () => {
    if (state.ws !== socket) return;
    setConnection('offline', 'RECONNECTING');
    clearTimeout(state.reconnectTimer);
    state.reconnectTimer = window.setTimeout(connectWebSocket, state.reconnectDelay);
    state.reconnectDelay = Math.min(state.reconnectDelay * 2, 15000);
  });
}

function startClock() {
  const update = () => {
    $('system-clock').textContent = new Intl.DateTimeFormat('en-IN', {
      hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
    }).format(new Date());
  };
  update();
  window.setInterval(update, 1000);
}

function bindControls() {
  $('view-2d-button').addEventListener('click', () => setView('2d'));
  $('view-3d-button').addEventListener('click', () => setView('3d'));
  $('map-match-mode').addEventListener('click', () => setMatchMode(!state.mapMatchEnabled));
  $('solve-flow-button').addEventListener('click', solveScenario);
  for (const prefix of ['gate1', 'paud', 'exit']) {
    $(`${prefix}-range`).addEventListener('input', (event) => {
      $(`${prefix}-number`).value = event.target.value;
      updateScenarioControls(prefix);
    });
    $(`${prefix}-number`).addEventListener('input', (event) => {
      $(`${prefix}-range`).value = event.target.value;
      updateScenarioControls(prefix);
    });
    $(`${prefix}-number`).addEventListener('change', () => updateScenarioControls(prefix));
  }
  $('gps-form').addEventListener('submit', (event) => {
    event.preventDefault();
    submitGPSFix();
  });
}

async function initialize() {
  startClock();
  bindControls();
  updateScenarioControls(null);
  try {
    initMap();
    await loadNetwork();
  } catch (error) {
    setOverlayError(error.message);
  }
  connectWebSocket();
}

initialize();
