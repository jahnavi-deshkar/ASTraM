import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const ROAD_COLORS = Object.freeze({
  free: 0x22c55e,
  moderate: 0xeab308,
  warning: 0xf97316,
  severe: 0xef4444,
});

const BUILDING_DEFAULTS = Object.freeze({
  Saraswati: {
    displayName: 'Saraswati',
    description: 'Academic building',
  },
  Vishwakarma: {
    displayName: 'Vishwakarma',
    description: 'Academic building',
  },
  SportsComplex: {
    displayName: 'Sports Complex',
    description: 'Sports and recreation facility',
  },
});

let defaultViewer = null;

function injectTooltipStyles() {
  if (document.getElementById('astram-campus-tooltip-styles')) return;
  const style = document.createElement('style');
  style.id = 'astram-campus-tooltip-styles';
  style.textContent = `
    .astram-campus-tooltip {
      position: absolute; z-index: 20; display: none; min-width: 190px; max-width: 280px;
      padding: 12px 14px; border: 1px solid rgba(148,163,184,.35); border-radius: 10px;
      color: #f8fafc; background: rgba(15,23,42,.94); box-shadow: 0 12px 32px rgba(2,6,23,.3);
      font: 13px/1.45 system-ui, sans-serif; pointer-events: none; backdrop-filter: blur(8px);
    }
    .astram-campus-tooltip strong { display:block; margin-bottom:4px; color:#fff; font-size:14px; }
    .astram-campus-tooltip span { display:block; color:#cbd5e1; }
    .astram-campus-tooltip .astram-tooltip-meta { margin-top:7px; color:#94a3b8; font-size:11px; }
    .astram-campus-canvas { display:block; width:100%; height:100%; outline:none; }
  `;
  document.head.appendChild(style);
}

function roadIdFromObject(object) {
  const explicit = object.userData?.edgeId;
  if (typeof explicit === 'string' && explicit.length) return explicit;
  const match = /^Road_(.+)$/.exec(object.name || '');
  return match?.[1] ?? null;
}

function saturationEntries(data) {
  if (!data || typeof data !== 'object') return [];
  if (Array.isArray(data)) {
    return data
      .filter((item) => item && typeof item.edge_id === 'string')
      .map((item) => [item.edge_id, item.saturation_ratio]);
  }
  if (data.saturation_ratios && typeof data.saturation_ratios === 'object') {
    return Object.entries(data.saturation_ratios);
  }
  if (Array.isArray(data.edges)) {
    return saturationEntries(data.edges);
  }
  return Object.entries(data).filter(([, value]) => Number.isFinite(Number(value)));
}

function colorForSaturation(rawValue) {
  const rho = Number(rawValue);
  if (!Number.isFinite(rho) || rho < 0) return null;
  if (rho < 0.5) return ROAD_COLORS.free;
  if (rho < 0.75) return ROAD_COLORS.moderate;
  if (rho < 0.9) return ROAD_COLORS.warning;
  return ROAD_COLORS.severe;
}

export class ASTraMCampusViewer {
  constructor({
    container,
    assetUrl = '/static/assets/mit_wpu_campus.glb',
    websocketUrl,
    connectWebSocket = true,
    backgroundColor = 0x0b1220,
    onBuildingSelect = null,
    onLoad = null,
    onError = null,
  } = {}) {
    if (typeof document === 'undefined') {
      throw new Error('ASTraMCampusViewer requires a browser document');
    }
    this.container = typeof container === 'string'
      ? document.querySelector(container)
      : container;
    if (!this.container) {
      throw new Error('A valid campus viewer container element is required');
    }
    this.assetUrl = assetUrl;
    this.websocketUrl = websocketUrl || this._defaultWebSocketUrl();
    this.onBuildingSelect = onBuildingSelect;
    this.onLoad = onLoad;
    this.onError = onError;
    this.disposed = false;
    this.roadObjects = new Map();
    this._clonedMaterials = new Set();
    this._hoveredObject = null;
    this._reconnectDelayMs = 1000;
    this._maxReconnectDelayMs = 15000;
    this._reconnectTimer = null;
    this._socket = null;
    this._animationFrame = null;
    this._raycaster = new THREE.Raycaster();
    this._pointer = new THREE.Vector2();

    injectTooltipStyles();
    this.container.style.position ||= 'relative';
    this.canvas = document.createElement('canvas');
    this.canvas.className = 'astram-campus-canvas';
    this.canvas.tabIndex = 0;
    this.canvas.setAttribute('aria-label', 'Interactive 3D campus map');
    this.container.appendChild(this.canvas);
    this.tooltip = document.createElement('div');
    this.tooltip.className = 'astram-campus-tooltip';
    this.tooltip.setAttribute('role', 'tooltip');
    this.container.appendChild(this.tooltip);

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(backgroundColor);
    this.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 10000);
    this.camera.up.set(0, 1, 0);
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      alpha: false,
      powerPreference: 'high-performance',
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.1;

    this.scene.add(new THREE.HemisphereLight(0xdbeafe, 0x334155, 2.0));
    const sun = new THREE.DirectionalLight(0xfff4dc, 2.5);
    sun.position.set(-150, 250, 180);
    this.scene.add(sun);
    const fill = new THREE.DirectionalLight(0x93c5fd, 0.65);
    fill.position.set(120, 80, -100);
    this.scene.add(fill);

    this.controls = new OrbitControls(this.camera, this.canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.075;
    this.controls.screenSpacePanning = true;
    this.controls.maxPolarAngle = Math.PI * 0.49;
    this.controls.minDistance = 8;
    this.controls.maxDistance = 1800;
    this.controls.target.set(0, 0, 0);

    this._onResize = () => this.resize();
    this._onPointerMove = (event) => this._handlePointerMove(event);
    this._onPointerLeave = () => this._hideTooltip();
    this._onClick = (event) => this._handleClick(event);
    this.canvas.addEventListener('pointermove', this._onPointerMove);
    this.canvas.addEventListener('pointerleave', this._onPointerLeave);
    this.canvas.addEventListener('click', this._onClick);
    this.resizeObserver = new ResizeObserver(this._onResize);
    this.resizeObserver.observe(this.container);
    window.addEventListener('resize', this._onResize, { passive: true });

    this.modelRoot = null;
    this.ready = this._loadModel();
    this._animate();
    if (connectWebSocket) this.connectTrafficStream();
    defaultViewer = this;
  }

  _defaultWebSocketUrl() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${protocol}//${window.location.host}/ws/traffic-stream`;
  }

  _reportError(error) {
    if (typeof this.onError === 'function') this.onError(error);
    else console.error('[ASTraM campus viewer]', error);
  }

  _loadModel() {
    const loader = new GLTFLoader();
    return new Promise((resolve, reject) => {
      loader.load(
        this.assetUrl,
        (gltf) => {
          if (this.disposed) {
            this._disposeObject(gltf.scene);
            resolve(null);
            return;
          }
          this.modelRoot = gltf.scene;
          this.modelRoot.name ||= 'ASTraM_Campus';
          this.scene.add(this.modelRoot);
          this._indexRoads();
          this._fitCameraToModel();
          if (typeof this.onLoad === 'function') this.onLoad(gltf, this);
          resolve(gltf);
        },
        undefined,
        (error) => {
          this._reportError(error);
          reject(error);
        },
      );
    });
  }

  _indexRoads() {
    this.roadObjects.clear();
    if (!this.modelRoot) return;
    this.modelRoot.traverse((object) => {
      if (!object.isMesh) return;
      const edgeId = roadIdFromObject(object);
      if (!edgeId) return;
      this._makeRoadMaterialUnique(object);
      this.roadObjects.set(edgeId, object);
    });
  }

  _makeRoadMaterialUnique(mesh) {
    const clone = (material) => {
      const copy = material.clone();
      this._clonedMaterials.add(copy);
      return copy;
    };
    mesh.material = Array.isArray(mesh.material)
      ? mesh.material.map(clone)
      : clone(mesh.material);
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const material of materials) {
      if ('emissive' in material) {
        material.emissive.setHex(0x000000);
        material.emissiveIntensity = 0.55;
        material.needsUpdate = true;
      }
    }
  }

  _fitCameraToModel() {
    if (!this.modelRoot) return;
    const bounds = new THREE.Box3().setFromObject(this.modelRoot);
    const size = bounds.getSize(new THREE.Vector3());
    const center = bounds.getCenter(new THREE.Vector3());
    const largestDimension = Math.max(size.x, size.y, size.z, 1);
    const fov = THREE.MathUtils.degToRad(this.camera.fov);
    const distance = (largestDimension / (2 * Math.tan(fov / 2))) * 1.35;
    this.controls.target.copy(center);
    this.camera.position.set(
      center.x + distance * 0.82,
      center.y + distance * 0.88,
      center.z + distance * 0.82,
    );
    this.camera.near = Math.max(0.1, distance / 1000);
    this.camera.far = Math.max(1000, distance * 8);
    this.camera.updateProjectionMatrix();
    this.controls.minDistance = Math.max(3, largestDimension * 0.08);
    this.controls.maxDistance = largestDimension * 8;
    this.controls.update();
  }

  resize() {
    if (this.disposed) return;
    const width = Math.max(1, this.container.clientWidth);
    const height = Math.max(1, this.container.clientHeight);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height, false);
  }

  _animate() {
    if (this.disposed) return;
    this._animationFrame = requestAnimationFrame(() => this._animate());
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  _setPointer(event) {
    const rect = this.canvas.getBoundingClientRect();
    this._pointer.set(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this._raycaster.setFromCamera(this._pointer, this.camera);
    return this._raycaster.intersectObjects(this.modelRoot ? [this.modelRoot] : [], true);
  }

  _findBuildingObject(object) {
    let current = object;
    while (current && current !== this.modelRoot) {
      const name = current.name || '';
      if (current.userData?.interactiveType === 'building' || /^Building_/.test(name)) {
        return current;
      }
      current = current.parent;
    }
    return null;
  }

  _buildingMetadata(object) {
    const suffix = object.name.replace(/^Building_/, '');
    const defaults = BUILDING_DEFAULTS[suffix] || {
      displayName: suffix.replace(/([a-z])([A-Z])/g, '$1 $2'),
      description: 'Campus building',
    };
    return {
      displayName: object.userData?.displayName || defaults.displayName,
      description: object.userData?.description || defaults.description,
      floors: object.userData?.floors,
      heightMeters: object.userData?.heightMeters,
    };
  }

  _handlePointerMove(event) {
    if (!this.modelRoot) return;
    const intersections = this._setPointer(event);
    const buildingHit = intersections.find((hit) => this._findBuildingObject(hit.object));
    if (!buildingHit) {
      this._hoveredObject = null;
      this._hideTooltip();
      this.canvas.style.cursor = 'grab';
      return;
    }
    const building = this._findBuildingObject(buildingHit.object);
    this._hoveredObject = building;
    this.canvas.style.cursor = 'pointer';
    this._showTooltip(building, event);
  }

  _showTooltip(building, event) {
    const metadata = this._buildingMetadata(building);
    const title = document.createElement('strong');
    title.textContent = metadata.displayName;
    const description = document.createElement('span');
    description.textContent = metadata.description;
    this.tooltip.replaceChildren(title, description);
    const details = [];
    if (Number.isFinite(Number(metadata.floors))) details.push(`${metadata.floors} floors`);
    if (Number.isFinite(Number(metadata.heightMeters))) {
      details.push(`${Number(metadata.heightMeters).toFixed(1)} m`);
    }
    if (details.length) {
      const line = document.createElement('span');
      line.className = 'astram-tooltip-meta';
      line.textContent = details.join(' · ');
      this.tooltip.appendChild(line);
    }
    const rect = this.container.getBoundingClientRect();
    this.tooltip.style.left = `${Math.min(event.clientX - rect.left + 14, rect.width - 290)}px`;
    this.tooltip.style.top = `${Math.max(8, event.clientY - rect.top - 12)}px`;
    this.tooltip.style.display = 'block';
  }

  _hideTooltip() {
    this.tooltip.style.display = 'none';
  }

  _handleClick(event) {
    if (!this.modelRoot) return;
    const hit = this._setPointer(event).find((intersection) =>
      this._findBuildingObject(intersection.object),
    );
    if (!hit) return;
    const building = this._findBuildingObject(hit.object);
    if (typeof this.onBuildingSelect === 'function') {
      this.onBuildingSelect({ object: building, ...this._buildingMetadata(building) });
    }
  }

  update3DRoadColors(saturationData) {
    if (!saturationData || typeof saturationData !== 'object') return 0;
    let updated = 0;
    for (const [edgeId, value] of saturationEntries(saturationData)) {
      const object = this.roadObjects.get(String(edgeId));
      const color = colorForSaturation(value);
      if (!object || color === null) continue;
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) {
        if (!material) continue;
        const threeColor = new THREE.Color(color);
        if ('emissive' in material) {
          material.emissive.copy(threeColor);
          material.emissiveIntensity = 0.8;
        } else if ('color' in material) {
          material.color.copy(threeColor);
        }
        material.needsUpdate = true;
      }
      object.userData.saturationRatio = Number(value);
      object.userData.trafficState = Number(value) >= 0.9
        ? 'severe'
        : Number(value) >= 0.75
          ? 'warning'
          : Number(value) >= 0.5
            ? 'moderate'
            : 'free';
      updated += 1;
    }
    return updated;
  }

  connectTrafficStream() {
    if (this.disposed || !this.websocketUrl || typeof WebSocket === 'undefined') return;
    if (this._socket && [WebSocket.OPEN, WebSocket.CONNECTING].includes(this._socket.readyState)) return;
    const socket = new WebSocket(this.websocketUrl);
    this._socket = socket;
    socket.addEventListener('open', () => {
      this._reconnectDelayMs = 1000;
    });
    socket.addEventListener('message', (event) => {
      try {
        const packet = JSON.parse(event.data);
        this.update3DRoadColors(packet);
      } catch (error) {
        this._reportError(new Error(`Invalid traffic WebSocket message: ${error.message}`));
      }
    });
    socket.addEventListener('error', () => {
      socket.close();
    });
    socket.addEventListener('close', () => {
      if (this.disposed || this._socket !== socket) return;
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = window.setTimeout(() => {
        this.connectTrafficStream();
      }, this._reconnectDelayMs);
      this._reconnectDelayMs = Math.min(
        this._reconnectDelayMs * 2,
        this._maxReconnectDelayMs,
      );
    });
  }

  _disposeObject(root) {
    root.traverse((object) => {
      object.geometry?.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      for (const material of materials) material?.dispose();
    });
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    cancelAnimationFrame(this._animationFrame);
    clearTimeout(this._reconnectTimer);
    this._socket?.close(1000, 'Viewer disposed');
    this.resizeObserver.disconnect();
    window.removeEventListener('resize', this._onResize);
    this.canvas.removeEventListener('pointermove', this._onPointerMove);
    this.canvas.removeEventListener('pointerleave', this._onPointerLeave);
    this.canvas.removeEventListener('click', this._onClick);
    this.controls.dispose();
    for (const material of this._clonedMaterials) material.dispose();
    this.renderer.dispose();
    this.tooltip.remove();
    this.canvas.remove();
    if (defaultViewer === this) defaultViewer = null;
  }
}

export function update3DRoadColors(saturationData) {
  return defaultViewer ? defaultViewer.update3DRoadColors(saturationData) : 0;
}

export function createASTraMCampusViewer(options) {
  return new ASTraMCampusViewer(options);
}

export default ASTraMCampusViewer;
