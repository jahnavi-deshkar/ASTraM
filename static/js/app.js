import { ASTraMCampusViewer } from './three_campus_loader.js';

const API_BASE = window.ASTRAM_API_BASE || window.location.origin;
const IMAGE_WIDTH = 479;
const IMAGE_HEIGHT = 816;
const ROAD_COLORS = Object.freeze({ free: '#22c55e', moderate: '#eab308', warning: '#f97316', severe: '#ef4444' });
const PHASE_NAMES = Object.freeze({ north_approach: 'North approach', east_approach: 'East approach', south_approach: 'South approach', west_approach: 'West approach' });
const state = {
  map: null, roadLayer: null, network: null, calibration: null, edgeMetrics: new Map(),
  activeSignalPhases: {}, signalTiming: null, ws: null, reconnectDelay: 1000, reconnectTimer: null,
  mapMatchEnabled: false, mapMarker: null, selfMarker: null, vehicleMarkers: new Map(), viewer: null,
  currentView: '2d', lastSnapshotAt: null, solveBusy: false, gpsBusy: false,
  watchId: null, lastFixSentAt: 0,
};

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

function setConnection(stateName, label) { $('connection-status').dataset.state = stateName; $('connection-label').textContent = label; }
function setOverlayError(message) { $('map-error').textContent = message; $('map-error').classList.remove('is-hidden'); }
function clearOverlayError() { $('map-error').classList.add('is-hidden'); }
function saturationColor(ratio) {
  const rho = Number(ratio);
  if (!Number.isFinite(rho) || rho < 0.5) return ROAD_COLORS.free;
  if (rho < 0.75) return ROAD_COLORS.moderate;
  if (rho < 0.9) return ROAD_COLORS.warning;
  return ROAD_COLORS.severe;
}
function getEdgeMetric(edgeId) { return state.edgeMetrics.get(String(edgeId)) || {}; }
function updateEdgeMetric(edgeId, incoming) { const id = String(edgeId); state.edgeMetrics.set(id, { ...(state.edgeMetrics.get(id) || {}), ...incoming }); }

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  let data = {};
  try { data = await response.json(); } catch { /* Empty response bodies are valid for error handling. */ }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
  return data;
}

function imagePixelToLatLng(x, mapY) {
  const c = state.calibration;
  const y = IMAGE_HEIGHT - mapY;
  return [c.north_lat - (y / IMAGE_HEIGHT) * (c.north_lat - c.south_lat), c.west_lon + (x / IMAGE_WIDTH) * (c.east_lon - c.west_lon)];
}
function latLngToImagePixel(latitude, longitude) {
  const c = state.calibration;
  return [((longitude - c.west_lon) / (c.east_lon - c.west_lon)) * IMAGE_WIDTH, ((c.north_lat - latitude) / (c.north_lat - c.south_lat)) * IMAGE_HEIGHT];
}
function geoToMap(latitude, longitude) { const [x, y] = latLngToImagePixel(latitude, longitude); return [IMAGE_HEIGHT - y, x]; }

function initMap() {
  if (!window.L) throw new Error('Leaflet failed to load. Check the browser connection to its CDN.');
  state.map = L.map('campus-map', { crs: L.CRS.Simple, zoomControl: true, minZoom: -1, maxZoom: 3, preferCanvas: true, attributionControl: false, maxBoundsViscosity: 0.8 });
  state.map.setView([IMAGE_HEIGHT / 2, IMAGE_WIDTH / 2], 0);
  L.imageOverlay('/static/assets/mit_wpu_campus_layout.png', [[0, 0], [IMAGE_HEIGHT, IMAGE_WIDTH]], { interactive: false, opacity: 1 }).addTo(state.map);
  state.roadLayer = L.layerGroup().addTo(state.map);
  state.map.setMaxBounds([[-15, -12], [IMAGE_HEIGHT + 15, IMAGE_WIDTH + 12]]);
  state.map.on('click', (event) => {
    if (!state.mapMatchEnabled || !state.calibration) return;
    const [latitude, longitude] = imagePixelToLatLng(event.latlng.lng, event.latlng.lat);
    requestMapMatchAt(latitude, longitude);
  });
}

function roadStyle(feature) {
  const props = feature.properties || {};
  const metric = getEdgeMetric(props.id);
  return { color: saturationColor(metric.saturation_ratio ?? props.saturation_ratio ?? 0), weight: 5, opacity: 0.95, lineCap: 'round', lineJoin: 'round' };
}
function bindRoadPopup(feature, layer) {
  const props = feature.properties || {};
  layer.on('click', () => {
    const metric = getEdgeMetric(props.id);
    const number = (value, digits = 1) => Number.isFinite(Number(value)) ? Number(value).toFixed(digits) : '—';
    layer.bindPopup(`<div class="edge-popup"><strong>${escapeHtml(props.name || 'Campus road segment')} <span class="edge-id">${escapeHtml(props.id || '')}</span></strong><div class="edge-popup-grid"><span>Flow</span><b>${number(metric.flow ?? props.real_time_flow)} veh/hr</b><span>Capacity</span><b>${number(props.capacity, 0)} veh/hr</b><span>Saturation</span><b>${number((metric.saturation_ratio ?? props.saturation_ratio) * 100)}%</b><span>Active devices</span><b>${number(metric.active_device_count ?? props.active_device_count, 0)}</b><span>Density</span><b>${number(metric.crowd_density_people_per_100m ?? props.crowd_density_people_per_100m)} / 100m</b><span>BPR delay</span><b>${number(metric.delay_sec ?? props.delay_sec)} sec</b><span>Effective speed</span><b>${number(metric.effective_speed_kmh ?? props.effective_speed_kmh)} km/h</b></div></div>`, { maxWidth: 290 }).openPopup();
  });
}

async function loadNetwork() {
  try {
    const network = await apiRequest('/api/v1/network', { method: 'GET', headers: {} });
    state.network = network;
    state.calibration = network.metadata?.layout_calibration;
    if (!state.calibration || Number(state.calibration.width_px) !== IMAGE_WIDTH || Number(state.calibration.height_px) !== IMAGE_HEIGHT) throw new Error('Campus poster calibration is missing or does not match the layout image dimensions.');
    state.roadLayer.clearLayers();
    for (const feature of network.features || []) {
      const props = feature.properties || {};
      updateEdgeMetric(props.id, { flow: props.real_time_flow, saturation_ratio: props.saturation_ratio, travel_time_sec: props.travel_time_sec, delay_sec: props.delay_sec, effective_speed_kmh: props.effective_speed_kmh, capacity: props.capacity, name: props.name, active_device_count: props.active_device_count, crowd_density_people_per_100m: props.crowd_density_people_per_100m });
      const pixels = props.layout_coordinates;
      if (!Array.isArray(pixels) || pixels.length < 2) continue;
      const line = L.polyline(pixels.map(([x, y]) => [IMAGE_HEIGHT - Number(y), Number(x)]), roadStyle(feature));
      line.feature = feature;
      bindRoadPopup(feature, line);
      state.roadLayer.addLayer(line);
    }
    state.map.fitBounds([[0, 0], [IMAGE_HEIGHT, IMAGE_WIDTH]], { padding: [8, 8] });
    $('map-layer-count').textContent = `${state.roadLayer.getLayers().length} directed links · campus schematic`;
    $('map-loading').classList.add('is-hidden');
    updateMapColors(); renderLiveMetrics(); renderAlertFeed();
  } catch (error) {
    $('map-loading').classList.add('is-hidden');
    setOverlayError(`Could not load the campus schematic: ${error.message}`);
  }
}

function updateMapColors() {
  for (const layer of state.roadLayer?.getLayers() || []) layer.setStyle(roadStyle(layer.feature));
  if (state.viewer) state.viewer.update3DRoadColors(Object.fromEntries([...state.edgeMetrics].map(([id, metric]) => [id, metric.saturation_ratio ?? 0])));
}
function updateLiveEdges(edges) {
  if (!Array.isArray(edges)) return;
  for (const edge of edges) if (typeof edge.edge_id === 'string') updateEdgeMetric(edge.edge_id, { flow: edge.flow, saturation_ratio: edge.saturation_ratio, travel_time_sec: edge.travel_time_sec, delay_sec: edge.delay_sec, effective_speed_kmh: edge.effective_speed_kmh, capacity_warning: edge.capacity_warning, active_device_count: edge.active_device_count, crowd_density_people_per_100m: edge.crowd_density_people_per_100m });
  updateMapColors(); renderLiveMetrics(); renderAlertFeed();
}
function updateDeviceCounts(aggregation) {
  if (!aggregation) return;
  const count = Number(aggregation.active_device_count) || 0;
  $('active-device-count').textContent = count.toLocaleString();
  $('map-active-device-count').textContent = count.toLocaleString();
  const counts = aggregation.edge_device_counts || {};
  for (const [edgeId, countOnEdge] of Object.entries(counts)) updateEdgeMetric(edgeId, { active_device_count: Number(countOnEdge) || 0, crowd_density_people_per_100m: Number(aggregation.edge_density?.[edgeId]?.people_per_100m) || 0 });
}
function renderLiveMetrics() {
  const metrics = [...state.edgeMetrics.values()]; if (!metrics.length) return;
  const saturation = metrics.map((m) => Number(m.saturation_ratio)).filter(Number.isFinite);
  const flows = metrics.map((m) => Number(m.flow)).filter(Number.isFinite);
  const averageSaturation = saturation.length ? saturation.reduce((a, b) => a + b, 0) / saturation.length : 0;
  const averageFlow = flows.length ? flows.reduce((a, b) => a + b, 0) / flows.length : 0;
  const warnings = saturation.filter((rho) => rho >= 0.75).length;
  $('total-flow').textContent = Math.round(averageFlow).toLocaleString(); $('average-saturation').textContent = (averageSaturation * 100).toFixed(1);
  $('warning-count').textContent = warnings.toLocaleString(); $('warning-summary').textContent = warnings ? 'Preemptive action recommended' : '75% buffer threshold';
  $('alert-count-badge').textContent = String(warnings); $('alert-count-badge').classList.toggle('has-alerts', warnings > 0);
  $('flow-snapshot').textContent = `${flows.length} road links reporting`;
}
function renderAlertFeed() {
  const warnings = [...state.edgeMetrics].map(([edgeId, metric]) => ({ edgeId, ...metric, rho: Number(metric.saturation_ratio) })).filter((item) => Number.isFinite(item.rho) && item.rho >= 0.75).sort((a, b) => b.rho - a.rho);
  const feed = $('alert-feed');
  if (!warnings.length) { feed.innerHTML = '<div class="alert-empty"><span>✓</span><p>No links above the 75% capacity buffer.</p></div>'; return; }
  feed.replaceChildren(...warnings.slice(0, 8).map((item) => {
    const card = document.createElement('div'); card.className = `alert-item${item.rho >= 0.9 ? ' severe' : ''}`;
    const title = document.createElement('div'); title.className = 'alert-title'; title.textContent = `${item.name || item.edgeId} · ${item.edgeId}`;
    const detail = document.createElement('div'); detail.className = 'alert-detail'; detail.textContent = `${item.active_device_count || 0} active device(s) · ${Number(item.crowd_density_people_per_100m || 0).toFixed(1)} people/100m`;
    const badge = document.createElement('span'); badge.className = 'alert-badge'; badge.textContent = `${(item.rho * 100).toFixed(1)}%`;
    card.append(title, detail, badge); return card;
  }));
}

function renderSignalTiming(timing) {
  if (!timing) return;
  state.signalTiming = timing; $('cycle-value').textContent = Number(timing.cycle_time_sec || 0).toFixed(0); $('cycle-total').textContent = Number(timing.cycle_time_sec || 0).toFixed(0); $('amber-value').textContent = Number(timing.amber_clearance_sec || 0).toFixed(0);
  const greens = timing.green_phase_durations_sec || timing.green_times_sec || {}; const maxGreen = Math.max(1, ...Object.values(greens).map(Number)); const names = Object.keys(greens); const container = $('signal-phases'); if (!names.length) return;
  container.replaceChildren(...names.map((name) => {
    const card = document.createElement('div'); card.className = `signal-phase${state.activeSignalPhases[name] === 'green' ? ' is-green' : ''}`; card.dataset.phase = name;
    const top = document.createElement('div'); top.className = 'signal-phase-top'; const title = document.createElement('span'); title.className = 'signal-phase-name'; title.textContent = PHASE_NAMES[name] || name.replaceAll('_', ' ');
    const light = document.createElement('i'); light.className = 'signal-light'; light.setAttribute('aria-label', state.activeSignalPhases[name] || 'inactive'); top.append(title, light);
    const seconds = document.createElement('p'); seconds.className = 'signal-seconds'; seconds.append(document.createTextNode(Number(greens[name]).toFixed(1))); const unit = document.createElement('small'); unit.textContent = 'sec green'; seconds.append(unit);
    const track = document.createElement('div'); track.className = 'signal-track'; const fill = document.createElement('i'); fill.style.width = `${Math.max(0, Math.min(100, Number(greens[name]) / maxGreen * 100))}%`; track.append(fill); card.append(top, seconds, track); return card;
  })); updateSignalLights();
}
function updateSignalLights() {
  document.querySelectorAll('.signal-phase').forEach((card) => { const phase = state.activeSignalPhases[card.dataset.phase]; card.classList.toggle('is-green', phase === 'green'); card.classList.toggle('is-amber', phase === 'amber'); card.querySelector('.signal-light')?.setAttribute('aria-label', phase || 'inactive'); });
}

function setView(view) {
  state.currentView = view; const is3d = view === '3d'; $('campus-map').classList.toggle('is-visible', !is3d); $('campus-3d').classList.toggle('is-visible', is3d);
  $('view-2d-button').classList.toggle('is-active', !is3d); $('view-3d-button').classList.toggle('is-active', is3d); $('view-2d-button').setAttribute('aria-pressed', String(!is3d)); $('view-3d-button').setAttribute('aria-pressed', String(is3d)); $('map-heading').textContent = is3d ? 'MIT-WPU 3D campus' : 'MIT-WPU live map';
  if (is3d) { ensure3DViewer(); requestAnimationFrame(() => state.viewer?.resize()); } else requestAnimationFrame(() => state.map?.invalidateSize(false));
}
function ensure3DViewer() {
  if (state.viewer) return;
  try {
    state.viewer = new ASTraMCampusViewer({ container: $('campus-3d'), assetUrl: '/static/assets/mit_wpu_campus.glb', connectWebSocket: false, onError: (error) => setOverlayError(`3D campus asset unavailable: ${error.message}`) });
    state.viewer.ready.then(() => { clearOverlayError(); updateMapColors(); state.viewer.resize(); }).catch(() => {});
  } catch (error) { setOverlayError(`3D viewer could not start: ${error.message}`); }
}

function setMatchMode(enabled) {
  state.mapMatchEnabled = enabled; const button = $('map-match-mode'); button.setAttribute('aria-pressed', String(enabled)); button.textContent = enabled ? '× Stop map snap testing' : '⌖ Click map to test GPS snap'; $('campus-map').style.cursor = enabled ? 'crosshair' : '';
}
async function requestMapMatchAt(latitude, longitude) { $('gps-latitude').value = Number(latitude).toFixed(6); $('gps-longitude').value = Number(longitude).toFixed(6); await submitGPSFix(latitude, longitude); }
async function submitGPSFix(latitude = Number($('gps-latitude').value), longitude = Number($('gps-longitude').value), options = {}) {
  if (state.gpsBusy || !Number.isFinite(Number(latitude)) || !Number.isFinite(Number(longitude))) return;
  state.gpsBusy = true; if (!options.silent) { $('gps-error').classList.add('is-hidden'); $('gps-submit').disabled = true; $('gps-submit').textContent = 'Matching location…'; }
  try {
    const headingValue = options.heading ?? $('gps-heading').value; const speedMps = options.speedMps;
    const payload = { device_id: $('gps-device').value.trim(), latitude: Number(latitude), longitude: Number(longitude), heading: headingValue === '' || headingValue == null ? null : Number(headingValue), speed: speedMps == null ? (Number.isFinite(Number($('gps-speed').value)) ? Number($('gps-speed').value) / 3.6 : null) : speedMps };
    const result = await apiRequest('/api/v1/map-match', { method: 'POST', body: JSON.stringify(payload) }); renderGPSResult(result, Number(latitude), Number(longitude));
  } catch (error) { if (!options.silent) { $('gps-error').textContent = error.message; $('gps-error').classList.remove('is-hidden'); } }
  finally { state.gpsBusy = false; if (!options.silent) { $('gps-submit').disabled = false; $('gps-submit').textContent = 'Test snap to road'; } }
}
function renderGPSResult(result, latitude = Number($('gps-latitude').value), longitude = Number($('gps-longitude').value)) {
  $('gps-result').classList.remove('is-hidden'); const badge = $('gps-network-badge'); badge.textContent = result.is_on_network ? 'ON NETWORK' : 'OFF ROAD'; badge.classList.toggle('is-on', result.is_on_network); badge.classList.toggle('is-off', !result.is_on_network);
  $('gps-road-name').textContent = result.is_on_network ? `${result.matched_edge_name} · ${result.matched_edge_id}` : 'Off-Road / Pedestrian Path';
  $('gps-distance').textContent = result.cross_track_distance_m == null ? '—' : `${Number(result.cross_track_distance_m).toFixed(2)} m`; $('gps-heading-delta').textContent = result.heading_delta_deg == null ? '—' : `${Number(result.heading_delta_deg).toFixed(1)}°`; $('gps-confidence').textContent = `${(Number(result.confidence_score) * 100).toFixed(0)}%`;
  const point = result.is_on_network ? [result.snapped_latitude, result.snapped_longitude] : [latitude, longitude];
  if (state.mapMarker) state.map.removeLayer(state.mapMarker);
  state.mapMarker = L.circleMarker(geoToMap(point[0], point[1]), { radius: 6, color: result.is_on_network ? '#0ea5e9' : '#f97316', weight: 2, fillColor: result.is_on_network ? '#38bdf8' : '#fb923c', fillOpacity: 0.95 }).addTo(state.map).bindTooltip(result.is_on_network ? 'Matched road location' : 'Off-road GPS fix');
}

function deviceId() {
  const key = 'astram-device-id'; let id = window.localStorage.getItem(key);
  if (!id) { id = `browser-${window.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(36).slice(2)}`}`; window.localStorage.setItem(key, id); }
  $('gps-device').value = id; return id;
}
function setLocationButtons(active, label) {
  for (const id of ['share-location-button', 'share-live-location-map']) { const button = $(id); button.setAttribute('aria-pressed', String(active)); button.classList.toggle('is-sharing', active); }
  $('share-location-label').textContent = label;
  const mapButton = $('share-live-location-map'); mapButton.textContent = active ? '■ Stop Live Location' : '⌖ Share My Live Location';
}
function locationError(error) {
  const messages = { 1: 'Location permission was denied. Allow location access in your browser settings to share a fix.', 2: 'Your device could not determine its location.', 3: 'Location request timed out. ASTraM will continue waiting for a GPS fix.' };
  $('gps-error').textContent = messages[error.code] || 'Browser location is unavailable.'; $('gps-error').classList.remove('is-hidden'); setLocationButtons(false, 'Share My Live Location');
}
function onGeolocation(position) {
  const { latitude, longitude, heading, speed } = position.coords;
  if (state.calibration) {
    if (!state.selfMarker) state.selfMarker = L.marker(geoToMap(latitude, longitude), { icon: L.divIcon({ className: 'you-are-here-marker', html: '<span class="you-are-here-pin"></span><span class="you-are-here-label">YOU ARE HERE</span>', iconSize: [112, 42], iconAnchor: [15, 34] }), zIndexOffset: 1200 }).addTo(state.map);
    else state.selfMarker.setLatLng(geoToMap(latitude, longitude));
  }
  $('gps-latitude').value = latitude.toFixed(6); $('gps-longitude').value = longitude.toFixed(6);
  if (heading != null && Number.isFinite(heading)) $('gps-heading').value = Math.round(heading);
  if (speed != null && Number.isFinite(speed)) $('gps-speed').value = (speed * 3.6).toFixed(1);
  const now = Date.now(); if (now - state.lastFixSentAt >= 1800) { state.lastFixSentAt = now; submitGPSFix(latitude, longitude, { silent: true, heading, speedMps: speed }); }
}
function toggleLiveLocation() {
  if (state.watchId != null) { navigator.geolocation.clearWatch(state.watchId); state.watchId = null; setLocationButtons(false, 'Share My Live Location'); return; }
  if (!navigator.geolocation) { $('gps-error').textContent = 'This browser does not support live location tracking.'; $('gps-error').classList.remove('is-hidden'); return; }
  if (window.location.protocol !== 'https:' && window.location.hostname !== 'localhost' && window.location.hostname !== '127.0.0.1') { $('gps-error').textContent = 'Browser GPS requires HTTPS or localhost.'; $('gps-error').classList.remove('is-hidden'); return; }
  deviceId(); $('gps-error').classList.add('is-hidden'); setLocationButtons(true, 'Stop Sharing Location');
  state.watchId = navigator.geolocation.watchPosition(onGeolocation, locationError, { enableHighAccuracy: true, maximumAge: 2000, timeout: 15000 });
}

function updateScenarioControls(changed) {
  let gate1 = Number($('gate1-number').value), cast = Number($('cast-number').value), exit = Number($('exit-number').value);
  if (![gate1, cast, exit].every(Number.isFinite)) return;
  gate1 = Math.max(0, Math.min(150, Math.round(gate1))); cast = Math.max(-140, Math.min(140, Math.round(cast))); exit = Math.max(0, Math.min(120, Math.round(exit)));
  if (changed === 'exit') cast = exit - gate1; else exit = gate1 + cast;
  const balanced = gate1 + cast === exit; const valid = balanced && exit >= 0 && exit <= 120;
  setInputPair('gate1', gate1); setInputPair('cast', cast); setInputPair('exit', exit);
  $('scenario-validation').classList.toggle('is-invalid', !valid); $('scenario-validation').textContent = valid ? 'Boundary flows balance. Gate 3 exit capacity: 120 veh/hr.' : 'Adjust Gate 1 and Cast Gate flows so their sum matches Gate 3 outflow (maximum 120 veh/hr).'; $('solve-flow-button').disabled = !valid || state.solveBusy;
}
function setInputPair(prefix, value) { $(`${prefix}-range`).value = String(value); $(`${prefix}-number`).value = String(value); $(`${prefix}-output`).textContent = String(value); }
async function solveScenario() {
  const gate1 = Number($('gate1-number').value), cast = Number($('cast-number').value), exit = Number($('exit-number').value);
  if (gate1 + cast !== exit || exit > 120 || exit < 0) return;
  state.solveBusy = true; $('solve-flow-button').disabled = true; $('solve-flow-button').innerHTML = '<span>⟳</span> Solving network…'; $('solve-error').classList.add('is-hidden');
  try {
    const result = await apiRequest('/api/v1/solve-flow', { method: 'POST', body: JSON.stringify({ node_1: gate1, node_7: cast, node_8: -exit }) });
    for (const [id, flow] of Object.entries(result.X || {})) updateEdgeMetric(id, { flow, saturation_ratio: result.saturation_ratios?.[id], delay_sec: result.bpr_delay_penalties_sec?.[id], effective_speed_kmh: result.effective_speeds_kmh?.[id], travel_time_sec: result.travel_times_sec?.[id] });
    renderSignalTiming(result.signal_timing); updateMapColors(); renderLiveMetrics(); renderAlertFeed(); $('flow-snapshot').textContent = `Residual ${Number(result.residual_error).toExponential(1)}`; $('last-update').textContent = `Scenario solved ${new Date().toLocaleTimeString()}`;
  } catch (error) { $('solve-error').textContent = error.message; $('solve-error').classList.remove('is-hidden'); }
  finally { state.solveBusy = false; $('solve-flow-button').innerHTML = '<span>⟳</span> Recalculate traffic flow'; updateScenarioControls(null); }
}

function updateFromTrafficState(packet) {
  if (!packet || typeof packet !== 'object') return;
  updateLiveEdges(packet.edges); updateDeviceCounts(packet.device_aggregation);
  if (packet.active_signal_phases && typeof packet.active_signal_phases === 'object') { state.activeSignalPhases = packet.active_signal_phases; if (packet.signal_timing && Object.keys(packet.signal_timing).length) renderSignalTiming(packet.signal_timing); updateSignalLights(); }
  if (Number.isFinite(Number(packet.simulation_tick))) $('simulation-tick').textContent = `Simulation tick ${packet.simulation_tick}`;
  if (Array.isArray(packet.vehicle_positions)) { updateVehicleMarkers(packet.vehicle_positions); $('flow-snapshot').title = `${packet.vehicle_positions.length} live device positions in stream`; }
  state.lastSnapshotAt = new Date(); $('last-update').textContent = `Live update ${state.lastSnapshotAt.toLocaleTimeString()}`;
  if (state.viewer) state.viewer.update3DRoadColors({ edges: packet.edges || [] });
}
function updateVehicleMarkers(vehicles) {
  if (!state.map || !state.calibration) return; const ids = new Set();
  for (const item of vehicles) {
    if (typeof item.vehicle_id !== 'string' || !Number.isFinite(Number(item.latitude)) || !Number.isFinite(Number(item.longitude))) continue;
    ids.add(item.vehicle_id); const point = geoToMap(Number(item.latitude), Number(item.longitude)); let marker = state.vehicleMarkers.get(item.vehicle_id);
    if (!marker) { marker = L.circleMarker(point, { radius: 4, color: '#e0f2fe', weight: 1.2, fillColor: '#2563eb', fillOpacity: 0.95 }).addTo(state.map); state.vehicleMarkers.set(item.vehicle_id, marker); }
    else marker.setLatLng(point);
    marker.setTooltipContent(`Live device · ${escapeHtml(item.edge_id || '')}`);
  }
  for (const [id, marker] of state.vehicleMarkers) if (!ids.has(id)) { state.map.removeLayer(marker); state.vehicleMarkers.delete(id); }
}
function connectWebSocket() {
  if (state.ws && [WebSocket.OPEN, WebSocket.CONNECTING].includes(state.ws.readyState)) return;
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'; const socket = new WebSocket(`${protocol}//${location.host}/ws/traffic-stream`); state.ws = socket; setConnection('connecting', 'CONNECTING');
  socket.addEventListener('open', () => { state.reconnectDelay = 1000; setConnection('online', 'ONLINE / STREAMING'); });
  socket.addEventListener('message', (event) => { try { updateFromTrafficState(JSON.parse(event.data)); } catch (error) { console.error('Could not process ASTraM traffic stream packet', error); } });
  socket.addEventListener('error', () => socket.close());
  socket.addEventListener('close', () => { if (state.ws !== socket) return; setConnection('offline', 'RECONNECTING'); clearTimeout(state.reconnectTimer); state.reconnectTimer = setTimeout(connectWebSocket, state.reconnectDelay); state.reconnectDelay = Math.min(state.reconnectDelay * 2, 15000); });
}
function startClock() { const update = () => { $('system-clock').textContent = new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date()); }; update(); setInterval(update, 1000); }
function bindControls() {
  $('view-2d-button').addEventListener('click', () => setView('2d')); $('view-3d-button').addEventListener('click', () => setView('3d')); $('map-match-mode').addEventListener('click', () => setMatchMode(!state.mapMatchEnabled)); $('solve-flow-button').addEventListener('click', solveScenario);
  $('share-location-button').addEventListener('click', toggleLiveLocation); $('share-live-location-map').addEventListener('click', toggleLiveLocation);
  for (const prefix of ['gate1', 'cast', 'exit']) { $(`${prefix}-range`).addEventListener('input', (event) => { $(`${prefix}-number`).value = event.target.value; updateScenarioControls(prefix === 'exit' ? 'exit' : prefix); }); $(`${prefix}-number`).addEventListener('input', (event) => { $(`${prefix}-range`).value = event.target.value; updateScenarioControls(prefix === 'exit' ? 'exit' : prefix); }); $(`${prefix}-number`).addEventListener('change', () => updateScenarioControls(prefix === 'exit' ? 'exit' : prefix)); }
  $('gps-form').addEventListener('submit', (event) => { event.preventDefault(); submitGPSFix(); });
  deviceId(); window.addEventListener('beforeunload', () => { if (state.watchId != null) navigator.geolocation.clearWatch(state.watchId); });
}
async function initialize() {
  startClock(); bindControls(); updateScenarioControls(null);
  try { initMap(); await loadNetwork(); } catch (error) { setOverlayError(error.message); }
  connectWebSocket();
}
initialize();
