/**
 * turbine-scene.js
 *
 * Procedural, lifelike Babylon.js visualization of a Gaia-Wind 133-11kW
 * small wind turbine, driven by real telemetry (never simulated/fake motion).
 *
 * Model notes (documented fully in docs/GAIA133_VISUALIZATION.md):
 *  - Two-blade, downwind, free-yaw small turbine (NOT a generic 3-blade icon).
 *  - Approximate dimensions used for the procedural model, sourced from
 *    publicly published Gaia-Wind 133-11kW distributor/community spec
 *    sheets (rotor diameter ~13.3 m => "133", two blades, tubular tower,
 *    commonly offered at an 18 m hub height option). These are documented
 *    as *approximations* for a illustrative 3D model, not as verified
 *    engineering drawings.
 *
 * This file only builds/animates the scene. All telemetry decisions
 * (stale/stop/run, RPM math) live in turbine-telemetry.js and are unit
 * tested there without a browser.
 */
import { stepRotorAngle, deriveRotorState } from './turbine-telemetry.js';

const MAX_DPR = 1.5; // cap device pixel ratio so phones don't render at full native res
const MAX_FPS = 30; // cap render loop rate; this is a decorative illustration, not a game

export class GaiaWind133Scene {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {object} opts { reducedMotion: boolean }
   */
  constructor(canvas, opts = {}) {
    this.canvas = canvas;
    this.reducedMotion = !!opts.reducedMotion;
    this.disposed = false;
    this._rotorAngle = 0;
    this._lastFrameMs = null;
    this._lastRenderMs = 0;
    this._latestStatus = null;
    this._latestData = null;
    this._visible = true;

    this._buildScene();
    this._bindLifecycle();
  }

  _buildScene() {
    const BABYLON = window.BABYLON;
    const engine = new BABYLON.Engine(this.canvas, true, {
      preserveDrawingBuffer: false,
      stencil: false,
      antialias: true,
      disableWebGL2Support: false,
    });
    engine.setHardwareScalingLevel(1 / Math.min(window.devicePixelRatio || 1, MAX_DPR));
    this.engine = engine;

    const scene = new BABYLON.Scene(engine);
    scene.clearColor = new BABYLON.Color4(0.05, 0.08, 0.12, 1);
    scene.fogMode = BABYLON.Scene.FOGMODE_LINEAR;
    scene.fogColor = new BABYLON.Color3(0.65, 0.75, 0.85);
    scene.fogStart = 60;
    scene.fogEnd = 220;
    this.scene = scene;

    // --- Camera: a restrained orbit camera with limited range, framed like a
    // professional product/field photo rather than a free-fly game camera. ---
    const camera = new BABYLON.ArcRotateCamera(
      'camera',
      -Math.PI / 2.35,
      Math.PI / 2.55,
      42,
      new BABYLON.Vector3(0, 9, 0),
      scene
    );
    camera.lowerRadiusLimit = 22;
    camera.upperRadiusLimit = 70;
    camera.lowerBetaLimit = 0.35;
    camera.upperBetaLimit = Math.PI / 2.05; // don't let the camera dip below the ground
    camera.wheelDeltaPercentage = 0.01;
    camera.panningSensibility = 0; // no panning: keep the turbine centered
    camera.attachControl(this.canvas, true);
    this.camera = camera;

    // --- Lighting: sun-like directional key light + soft sky fill + shadows. ---
    const sun = new BABYLON.DirectionalLight('sun', new BABYLON.Vector3(-0.5, -1, 0.4), scene);
    sun.position = new BABYLON.Vector3(40, 60, -40);
    sun.intensity = 2.0;
    this.sun = sun;

    const sky = new BABYLON.HemisphericLight('sky', new BABYLON.Vector3(0, 1, 0), scene);
    sky.intensity = 0.55;
    sky.groundColor = new BABYLON.Color3(0.25, 0.3, 0.22);

    const shadowGenerator = new BABYLON.ShadowGenerator(1024, sun);
    shadowGenerator.usePercentageCloserFiltering = true;
    shadowGenerator.darkness = 0.35;
    this.shadowGenerator = shadowGenerator;

    // --- Ground: simple grass-toned field, bounded shadow receiver. ---
    const ground = BABYLON.MeshBuilder.CreateGround('ground', { width: 220, height: 220 }, scene);
    const groundMat = new BABYLON.StandardMaterial('groundMat', scene);
    groundMat.diffuseColor = new BABYLON.Color3(0.29, 0.38, 0.24);
    groundMat.specularColor = new BABYLON.Color3(0, 0, 0);
    ground.material = groundMat;
    ground.receiveShadows = true;

    // Pale sky-colored skydome (cheap, no texture download).
    const sky1 = BABYLON.MeshBuilder.CreateSphere('skydome', { diameter: 400, sideOrientation: BABYLON.Mesh.BACKSIDE }, scene);
    const skyMat = new BABYLON.StandardMaterial('skyMat', scene);
    skyMat.diffuseColor = new BABYLON.Color3(0.55, 0.72, 0.88);
    skyMat.emissiveColor = new BABYLON.Color3(0.45, 0.62, 0.8);
    skyMat.backFaceCulling = false;
    skyMat.disableLighting = true;
    sky1.material = skyMat;
    sky1.infiniteDistance = true;

    this._buildTurbine(shadowGenerator);
    this._buildLabels();
  }

  _buildTurbine(shadowGenerator) {
    const BABYLON = window.BABYLON;
    const scene = this.scene;
    const root = new BABYLON.TransformNode('turbineRoot', scene);

    // Approximate Gaia-Wind 133-11kW proportions (meters), documented in
    // docs/GAIA133_VISUALIZATION.md as sourced approximations:
    //   hub height ~18 m, rotor diameter ~13.3 m (two blades), downwind.
    const HUB_HEIGHT = 18;
    const ROTOR_RADIUS = 6.65;
    const TOWER_BASE_RADIUS = 0.42;
    const TOWER_TOP_RADIUS = 0.22;

    // Concrete base plinth.
    const base = BABYLON.MeshBuilder.CreateCylinder('base', { diameterTop: 1.6, diameterBottom: 2.0, height: 0.6 }, scene);
    base.position.y = 0.3;
    const baseMat = new BABYLON.StandardMaterial('baseMat', scene);
    baseMat.diffuseColor = new BABYLON.Color3(0.55, 0.55, 0.53);
    base.material = baseMat;
    base.parent = root;
    shadowGenerator.addShadowCaster(base);

    // Tapered tubular steel tower.
    const tower = BABYLON.MeshBuilder.CreateCylinder('tower', {
      height: HUB_HEIGHT - 0.6,
      diameterTop: TOWER_TOP_RADIUS * 2,
      diameterBottom: TOWER_BASE_RADIUS * 2,
      tessellation: 20,
    }, scene);
    tower.position.y = 0.6 + (HUB_HEIGHT - 0.6) / 2;
    const towerMat = new BABYLON.StandardMaterial('towerMat', scene);
    towerMat.diffuseColor = new BABYLON.Color3(0.82, 0.84, 0.86);
    towerMat.specularColor = new BABYLON.Color3(0.15, 0.15, 0.15);
    tower.material = towerMat;
    tower.parent = root;
    shadowGenerator.addShadowCaster(tower);

    // Nacelle (housing), slightly downwind-offset since the rotor is downwind.
    const nacelle = BABYLON.MeshBuilder.CreateBox('nacelle', { width: 1.0, height: 0.9, depth: 2.6 }, scene);
    nacelle.position.y = HUB_HEIGHT;
    nacelle.position.z = 0.9; // downwind of tower centerline
    const nacelleMat = new BABYLON.StandardMaterial('nacelleMat', scene);
    nacelleMat.diffuseColor = new BABYLON.Color3(0.9, 0.92, 0.94);
    nacelle.material = nacelleMat;
    nacelle.parent = root;
    shadowGenerator.addShadowCaster(nacelle);

    // Rotor pivot sits at the downwind end of the nacelle (free-yaw assembly).
    const rotorPivot = new BABYLON.TransformNode('rotorPivot', scene);
    rotorPivot.position = new BABYLON.Vector3(0, HUB_HEIGHT, 2.3);
    rotorPivot.parent = root;
    this.rotorPivot = rotorPivot;

    // Hub.
    const hub = BABYLON.MeshBuilder.CreateSphere('hub', { diameter: 0.9, segments: 10 }, scene);
    const hubMat = new BABYLON.StandardMaterial('hubMat', scene);
    hubMat.diffuseColor = new BABYLON.Color3(0.85, 0.85, 0.87);
    hub.material = hubMat;
    hub.parent = rotorPivot;
    shadowGenerator.addShadowCaster(hub);

    // Two tapered, twisted airfoil-ish blades (opposite sides of the hub;
    // teetering two-blade rotor is the distinctive Gaia-Wind silhouette).
    const bladeMat = new BABYLON.StandardMaterial('bladeMat', scene);
    bladeMat.diffuseColor = new BABYLON.Color3(0.93, 0.94, 0.95);
    bladeMat.specularColor = new BABYLON.Color3(0.2, 0.2, 0.2);

    this.blades = [];
    for (let i = 0; i < 2; i++) {
      const blade = this._buildBlade(scene, ROTOR_RADIUS, bladeMat);
      blade.rotation.z = i === 0 ? 0 : Math.PI; // opposite the hub, 180 degrees apart
      blade.parent = rotorPivot;
      shadowGenerator.addShadowCaster(blade);
      this.blades.push(blade);
    }

    this.turbineRoot = root;
  }

  /** A tapered + twisted blade approximated as a lofted ribbon of quads. */
  _buildBlade(scene, length, material) {
    const BABYLON = window.BABYLON;
    const sections = 10;
    const paths = [];
    for (let i = 0; i <= sections; i++) {
      const t = i / sections;
      const r = 0.35 + t * (length - 0.35); // distance from hub along blade
      const chord = 0.78 * (1 - 0.75 * t) + 0.05; // tapers toward the tip
      const twistDeg = 18 * (1 - t); // simple linear twist from root to tip
      const twist = (twistDeg * Math.PI) / 180;
      const halfChord = chord / 2;
      // Cross-section: a thin airfoil-like lens, rotated by the twist angle.
      const p1 = new BABYLON.Vector3(
        -halfChord * Math.cos(twist),
        r,
        -halfChord * Math.sin(twist)
      );
      const p2 = new BABYLON.Vector3(
        halfChord * Math.cos(twist),
        r,
        halfChord * Math.sin(twist)
      );
      paths.push([p1, p2]);
    }
    const ribbon = BABYLON.MeshBuilder.CreateRibbon('blade', { pathArray: paths, sideOrientation: BABYLON.Mesh.DOUBLESIDE }, scene);
    ribbon.material = material;
    return ribbon;
  }

  _buildLabels() {
    const BABYLON = window.BABYLON;
    const plane = BABYLON.MeshBuilder.CreatePlane('illustrationLabelPlane', { width: 10, height: 1.6 }, this.scene);
    plane.position = new BABYLON.Vector3(0, 1.1, 0);
    plane.billboardMode = BABYLON.Mesh.BILLBOARDMODE_Y;
    const dt = new BABYLON.DynamicTexture('illustrationLabelTex', { width: 1024, height: 160 }, this.scene, true);
    dt.hasAlpha = true;
    dt.drawText('3D ILLUSTRATION  \u2014  not a live camera view', 20, 100, '42px monospace', '#cde7ff', 'transparent', true);
    const mat = new BABYLON.StandardMaterial('illustrationLabelMat', this.scene);
    mat.diffuseTexture = dt;
    mat.emissiveTexture = dt;
    mat.opacityTexture = dt;
    mat.disableLighting = true;
    mat.backFaceCulling = false;
    plane.material = mat;
    this.illustrationLabel = plane;
  }

  _bindLifecycle() {
    this._onResize = () => this.engine && this.engine.resize();
    window.addEventListener('resize', this._onResize);

    this._onVisibility = () => {
      this._visible = document.visibilityState === 'visible';
    };
    document.addEventListener('visibilitychange', this._onVisibility);

    this._onReducedMotionChange = (e) => {
      this.reducedMotion = e.matches;
    };
    this._reducedMotionQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    this.reducedMotion = this._reducedMotionQuery.matches;
    if (this._reducedMotionQuery.addEventListener) {
      this._reducedMotionQuery.addEventListener('change', this._onReducedMotionChange);
    }

    this.engine.runRenderLoop(() => this._tick());
  }

  /** Called by the page's socket.io 'status' handler. */
  updateStatus(status) {
    this._latestStatus = { ...status, _receivedAtMs: Date.now() };
  }

  /** Called by the page's socket.io 'data' handler. */
  updateData(data) {
    this._latestData = data;
  }

  _tick() {
    if (this.disposed) return;
    if (!this._visible) return; // tab hidden: stop rendering/updating entirely

    const nowMs = performance.now();
    if (nowMs - this._lastRenderMs < 1000 / MAX_FPS) {
      return; // capped FPS; this is a decorative illustration
    }
    const dtSec = this._lastFrameMs === null ? 0 : (nowMs - this._lastFrameMs) / 1000;
    this._lastFrameMs = nowMs;
    this._lastRenderMs = nowMs;

    const nowWallMs = Date.now();
    const state = deriveRotorState(this._latestStatus, this._latestData, nowWallMs);
    this.lastState = state;

    if (!this.reducedMotion && state.spinning) {
      this._rotorAngle = stepRotorAngle(this._rotorAngle, state.rpm, dtSec);
    }
    // Reduced motion or stopped/stale: rotor angle is simply not advanced
    // (freeze in place), matching the "no fake wobble" requirement.
    if (this.rotorPivot) {
      this.rotorPivot.rotation.z = this._rotorAngle;
    }

    this.scene.render();
  }

  dispose() {
    this.disposed = true;
    window.removeEventListener('resize', this._onResize);
    document.removeEventListener('visibilitychange', this._onVisibility);
    if (this._reducedMotionQuery && this._reducedMotionQuery.removeEventListener) {
      this._reducedMotionQuery.removeEventListener('change', this._onReducedMotionChange);
    }
    if (this.engine) {
      this.engine.stopRenderLoop();
    }
    if (this.scene) {
      this.scene.dispose();
    }
    if (this.engine) {
      this.engine.dispose();
    }
  }
}

/**
 * Entry point used by templates/index.html. Guards against: no WebGL,
 * Babylon.js failing to load, and double-initialization on socket reconnect.
 */
export function initTurbineViz(canvas, fallbackEl) {
  if (window.__turbineVizInstance) {
    return window.__turbineVizInstance; // never duplicate the engine/render loop
  }
  if (!window.BABYLON) {
    if (fallbackEl) fallbackEl.hidden = false;
    if (canvas) canvas.hidden = true;
    return null;
  }
  let supportsWebGL = false;
  try {
    supportsWebGL = !!window.BABYLON.Engine.isSupported();
  } catch (e) {
    supportsWebGL = false;
  }
  if (!supportsWebGL) {
    if (fallbackEl) fallbackEl.hidden = false;
    if (canvas) canvas.hidden = true;
    return null;
  }
  try {
    const reducedMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const instance = new GaiaWind133Scene(canvas, { reducedMotion });
    window.__turbineVizInstance = instance;
    if (fallbackEl) fallbackEl.hidden = true;
    if (canvas) canvas.hidden = false;
    return instance;
  } catch (e) {
    console.error('Gaia-Wind 133 visualization failed to initialize:', e);
    if (fallbackEl) fallbackEl.hidden = false;
    if (canvas) canvas.hidden = true;
    return null;
  }
}
