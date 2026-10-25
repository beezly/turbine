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
import { stepRotorAngle, deriveRotorState, deriveWindState } from './turbine-telemetry.js';

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
    // Pale horizon haze (close to the sky gradient's horizon colour), starting
    // well beyond the turbine so only the far field dissolves into it.
    scene.fogColor = new BABYLON.Color3(0.78, 0.84, 0.88);
    scene.fogStart = 80;
    scene.fogEnd = 195; // fully hazed just inside the 200 m sky dome, which clips the ground
    this.scene = scene;

    // --- Camera: a restrained orbit camera, slight three-quarter yaw so
    // both blades read as a disc rather than edge-on as a line, framed
    // like a close field photo. Target/radius are NOT fixed magic
    // numbers: they are computed in _fitCameraToAspect() from the
    // turbine's actual geometric bounding box (computed after
    // _buildTurbine() runs) so the full tower+nacelle+swept rotor always
    // fits the viewport with margin, on any aspect ratio, instead of
    // clipping at the top on narrow/mobile canvases as the previous
    // hand-tuned constants did. ---
    // Composition per field-siting feedback: viewer stands inside the
    // field (SE of the turbine) looking back toward the NW corner where
    // the turbine is tucked near the wall junction -- alpha in the SE
    // quadrant (both x,z positive camera offset) looking NW at the origin.
    const camera = new BABYLON.ArcRotateCamera(
      'camera',
      Math.PI / 4.4, // SE-quadrant azimuth: camera sits inside the field, looking NW
      Math.PI / 2.55,
      24,
      new BABYLON.Vector3(0, 10, 1.5),
      scene
    );
    camera.lowerRadiusLimit = 8;
    // Raised from 60: the swept-rotor-disc bbox fit (see _fitCameraToAspect)
    // legitimately needs more clearance than the old instantaneous-blade
    // bbox did, and this cap was silently clamping the camera too close,
    // causing the exact top/bottom rotor clipping being fixed.
    camera.upperRadiusLimit = 90;
    camera.lowerBetaLimit = 0.5;
    camera.upperBetaLimit = Math.PI / 2.1; // don't let the camera dip below the ground
    camera.wheelDeltaPercentage = 0.01;
    camera.panningSensibility = 0; // no panning: keep the turbine centered
    camera.minZ = 0.5;
    camera.attachControl(this.canvas, true);
    this.camera = camera;

    // --- Lighting: a clearly directional "sun" (low-ish angle, so it casts
    // a visible, legible shadow instead of a flat near-overhead light) +
    // a dim sky fill so shadow sides aren't pure black. ---
    const sun = new BABYLON.DirectionalLight('sun', new BABYLON.Vector3(-0.55, -0.72, 0.42), scene);
    sun.position = new BABYLON.Vector3(28, 34, -22);
    sun.intensity = 2.6;
    sun.diffuse = new BABYLON.Color3(1.0, 0.97, 0.9);
    sun.specular = new BABYLON.Color3(1.0, 0.98, 0.92);
    this.sun = sun;

    const sky = new BABYLON.HemisphericLight('sky', new BABYLON.Vector3(0, 1, 0), scene);
    sky.intensity = 0.32;
    sky.diffuse = new BABYLON.Color3(0.65, 0.75, 0.88);
    sky.groundColor = new BABYLON.Color3(0.22, 0.24, 0.2);

    const shadowGenerator = new BABYLON.ShadowGenerator(1024, sun);
    shadowGenerator.usePercentageCloserFiltering = true;
    shadowGenerator.darkness = 0.45;
    shadowGenerator.bias = 0.002;
    this.shadowGenerator = shadowGenerator;

    // The ground is the wheat canopy surface: built with the crop in _buildWheat().

    // --- Sky: a vertical gradient (darker/more saturated blue at the
    // zenith fading to a pale, slightly warm horizon) instead of one flat
    // pale-blue band, built with a small dynamic texture (no external
    // image download). ---
    const sky1 = BABYLON.MeshBuilder.CreateSphere('skydome', { diameter: 400, sideOrientation: BABYLON.Mesh.BACKSIDE, segments: 12 }, scene);
    const skyMat = new BABYLON.StandardMaterial('skyMat', scene);
    const skyTex = new BABYLON.DynamicTexture('skyTex', { width: 16, height: 256 }, scene, false);
    const sctx = skyTex.getContext();
    const grad = sctx.createLinearGradient(0, 0, 0, 256);
    // v runs zenith (0) -> nadir (1), so the horizon is v=0.5; the lower half
    // is hidden by the field and stays at the haze colour.
    grad.addColorStop(0, '#2f5d8f');    // zenith: deeper, more saturated blue
    grad.addColorStop(0.3, '#6f9bc8');  // mid sky
    grad.addColorStop(0.45, '#b4cbdd'); // near horizon: pale, slightly hazy
    grad.addColorStop(0.5, '#c7d6e0');  // horizon haze, = scene.fogColor so the field dissolves into it
    grad.addColorStop(1, '#c7d6e0');
    sctx.fillStyle = grad;
    sctx.fillRect(0, 0, 16, 256);
    skyTex.update();
    skyMat.diffuseTexture = skyTex;
    skyMat.emissiveTexture = skyTex;
    skyMat.backFaceCulling = false;
    skyMat.disableLighting = true;
    sky1.material = skyMat;
    sky1.infiniteDistance = true;
    sky1.applyFog = false; // the gradient already carries the horizon haze

    this._buildTurbine(shadowGenerator);
    this._buildField(shadowGenerator);
    this._buildWheat();
    // NOTE: the in-scene billboard "3D ILLUSTRATION" label plane
    // (_buildLabels(), still defined below for reference/possible reuse)
    // is intentionally NOT built here anymore. It rendered as illegible
    // tiny text floating near the tower base/mid-left in real
    // screenshots -- a stray debug-looking artifact. The illustration
    // disclaimer is already shown reliably via the HTML
    // .viz-illustration-note overlay in templates/index.html, so this
    // in-scene duplicate was redundant as well as broken.
    this._fitCameraToAspect();
    this._assertCameraFit();
  }

  /**
   * Indicative field siting, approximated from Andrew's aerial photo (NOT a
   * survey -- documented honestly in docs/GAIA133_VISUALIZATION.md). The
   * aerial crops the field's southern extent and carries no scale
   * reference, so these wall positions/lengths are a rough trace, not
   * measured geometry. Composition: turbine tucked into the NW corner near
   * a wall junction, long grass filling the field, low drystone walls
   * marking the boundary, a stony/scrub patch along the eastern boundary,
   * a loose stand of trees near the north wall.
   */
  _buildField(shadowGenerator) {
    const BABYLON = window.BABYLON;
    const scene = this.scene;

    // DELETED per explicit third-time review request: the drystone
    // wall segments and the rock cluster were read in real screenshots
    // as "scaffolding/a gate frame" and "traffic cones/paper cups"
    // respectively, not as deliberate field props. Per review direction
    // ("an empty wheat field is better than confusing props... if it
    // cannot be made to look deliberate, DELETE it and say you deleted
    // it"), both are removed entirely rather than re-tuned again. The
    // tree stand below is kept (it was not flagged as a problem on its
    // own) but is no longer paired with a wall silhouette behind it.
    this.wallMeshes = [];
    this.rockMeshes = [];

    // Loose stand of trees BEYOND the north wall (trunk + 2-3 stacked low
    // -poly cones, not a sphere canopy -- a sphere canopy under this
    // light read as a glossy green ball, and matte cones give a much
    // more legible "conifer-ish scale cue" silhouette from field distance
    // for a cheap mesh). 4-7m total height, matte throughout.
    const trunkMat = new BABYLON.StandardMaterial('trunkMat', scene);
    trunkMat.diffuseColor = new BABYLON.Color3(0.32, 0.24, 0.18);
    trunkMat.specularColor = new BABYLON.Color3(0.015, 0.015, 0.015);
    const canopyMat = new BABYLON.StandardMaterial('canopyMat', scene);
    canopyMat.diffuseColor = new BABYLON.Color3(0.18, 0.3, 0.15);
    canopyMat.specularColor = new BABYLON.Color3(0.01, 0.01, 0.01);
    // Repositioned using direct camera-projection measurement (verified
    // tip positions, not just base positions, clear every frame edge with
    // margin) after repeated corner-clipping regressions.
    const treeSpots = [
      { x: -16, z: 10, h: 4.4 },
      { x: -20, z: 12, h: 5.6 },
      { x: -24, z: 10, h: 5.0 },
      { x: -22, z: 14, h: 6.0 },
    ];
    this.treeMeshes = [];
    for (const { x: tx, z: tz, h } of treeSpots) {
      const trunkHeight = h * 0.32;
      const trunk = BABYLON.MeshBuilder.CreateCylinder('trunk', { height: trunkHeight, diameterTop: 0.18, diameterBottom: 0.28 }, scene);
      trunk.position.set(tx, trunkHeight / 2, tz);
      trunk.material = trunkMat;
      shadowGenerator.addShadowCaster(trunk);
      this.treeMeshes.push(trunk);
      // 3 stacked cones of decreasing diameter, tip-to-tip, forming a
      // simple conifer silhouette.
      const coneCount = 3;
      const canopyHeight = h - trunkHeight;
      for (let c = 0; c < coneCount; c++) {
        const frac = c / coneCount; // 0 (base) .. <1 (near tip)
        const coneH = canopyHeight / coneCount * 1.3;
        const diameter = (1 - frac * 0.8) * (h * 0.32);
        const cone = BABYLON.MeshBuilder.CreateCylinder('canopyCone', { height: coneH, diameterTop: 0, diameterBottom: diameter }, scene);
        cone.position.set(tx, trunkHeight + frac * canopyHeight * 0.75 + coneH / 2, tz);
        cone.material = canopyMat;
        shadowGenerator.addShadowCaster(cone);
        this.treeMeshes.push(cone);
      }
    }
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
    // Exposed so _fitCameraToAspect() can compute the full swept-rotor
    // disc analytically instead of relying on the instantaneous blade
    // mesh bbox (which under-measures whenever the blades aren't at their
    // vertical extreme, causing top/bottom clipping once they rotate).
    this.hubHeight = HUB_HEIGHT;
    this.rotorRadius = ROTOR_RADIUS;
    this.rotorPivotZ = 2.3;
    const TOWER_BASE_RADIUS = 0.42;
    const TOWER_TOP_RADIUS = 0.22;

    // Concrete base plinth.
    const base = BABYLON.MeshBuilder.CreateCylinder('base', { diameterTop: 1.6, diameterBottom: 2.0, height: 0.6 }, scene);
    base.position.y = 0.3;
    const baseMat = new BABYLON.StandardMaterial('baseMat', scene);
    baseMat.diffuseColor = new BABYLON.Color3(0.42, 0.42, 0.4);
    baseMat.specularColor = new BABYLON.Color3(0.05, 0.05, 0.05);
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
    // Tower: light grey galvanized/painted steel, modest specular highlight
    // so it reads as metal rather than flat plastic white.
    towerMat.diffuseColor = new BABYLON.Color3(0.74, 0.76, 0.78);
    towerMat.specularColor = new BABYLON.Color3(0.35, 0.35, 0.37);
    towerMat.specularPower = 48;
    tower.material = towerMat;
    tower.parent = root;
    shadowGenerator.addShadowCaster(tower);

    // Nacelle (housing), slightly downwind-offset since the rotor is downwind.
    const nacelle = BABYLON.MeshBuilder.CreateBox('nacelle', { width: 1.0, height: 0.9, depth: 2.6 }, scene);
    nacelle.position.y = HUB_HEIGHT;
    nacelle.position.z = 0.9; // downwind of tower centerline
    const nacelleMat = new BABYLON.StandardMaterial('nacelleMat', scene);
    // Nacelle housing: warmer, slightly darker off-white GRP shell (distinct
    // from both the cooler grey tower and the brighter blades).
    nacelleMat.diffuseColor = new BABYLON.Color3(0.8, 0.79, 0.74);
    nacelleMat.specularColor = new BABYLON.Color3(0.25, 0.25, 0.22);
    nacelleMat.specularPower = 32;
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
    // Hub: darker neutral grey so it visually anchors the blade roots
    // instead of blending into the blades.
    hubMat.diffuseColor = new BABYLON.Color3(0.38, 0.39, 0.4);
    hubMat.specularColor = new BABYLON.Color3(0.3, 0.3, 0.3);
    hub.material = hubMat;
    hub.parent = rotorPivot;
    shadowGenerator.addShadowCaster(hub);

    // Two tapered, twisted airfoil-ish blades (opposite sides of the hub;
    // teetering two-blade rotor is the distinctive Gaia-Wind silhouette).
    const bladeMat = new BABYLON.StandardMaterial('bladeMat', scene);
    // Blades: brightest surface in the scene (fiberglass white, the
    // classic small-turbine blade finish), clearly lighter than the
    // nacelle/tower/hub so the silhouette reads at a glance.
    bladeMat.diffuseColor = new BABYLON.Color3(0.95, 0.96, 0.97);
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

  /**
   * Ripe wheat field, driven by real wind_speed_mps intensity only.
   *
   * Two layers that share one colour palette and one gust-wave field:
   *  - Dense instanced tufts out to FIELD_RADIUS: curved stalks with nodding
   *    ears and splayed awns, bent along a length-preserving arc in the
   *    vertex shader.
   *  - A ground "canopy" surface. Under the tufts it is the deep shade
   *    between stalks; beyond CANOPY_START it rises to ear height and is
   *    shaded as the sunlit top of the crop, so the field carries on to the
   *    horizon instead of ending in a ring of stalks on bare soil.
   *
   * Honest limitations (also documented in docs/GAIA133_VISUALIZATION.md):
   *  - The travelling gust/wave PATTERN (which patches bend harder, when,
   *    and the NW->SE travel direction) is a simulated illustrative field,
   *    NOT measured local wind direction or gust data.
   *  - Only the overall bend/sway INTENSITY is tied to a real telemetry
   *    value (deriveWindState().intensity, 0..1 from wind_speed_mps).
   *  - No per-tuft CPU animation: all motion happens in GPU shaders driven by
   *    a handful of per-frame uniforms; per-tuft variation lives in
   *    thin-instance buffers written once at build time.
   */
  _buildWheat() {
    const BABYLON = window.BABYLON;
    const scene = this.scene;

    const isNarrow = (this.canvas.clientWidth || window.innerWidth || 1024) < 500;
    const TUFT_COUNT = isNarrow ? 26000 : 64000;
    const STALKS_PER_TUFT = 6;
    const FULL_RADIUS = 45;     // full-density stand out to here (m from the tower)
    const FIELD_RADIUS = 80;    // tufts thin out smoothly to none by here
    const EXCLUDE_RADIUS = 2.2; // keep the stand clear of the tower base/plinth
    const CANOPY_START = 46;    // ground rises from soil level here...
    const CANOPY_END = 70;      // ...to ear height here, hidden by the thinning tufts
    const CANOPY_HEIGHT = 0.82; // ripe wheat stands ~0.7-0.95 m (see tuft heights below)

    // mulberry32: the LCG-with-modulo used elsewhere in this file has
    // short-period low bits, which piles tens of thousands of tufts onto a
    // few thousand repeated spots.
    let seed = 84211;
    const rand = () => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };

    // --- Tuft geometry, in units of the tuft's height (instance y-scale) ---
    // Each vertex stores the ribbon CENTRE in `position` and its half-width
    // vector in `side`, so the shader can widen distant stalks to ~1 pixel:
    // millimetre-wide geometry otherwise aliases into sparkle at field
    // distance, which is what made the old field read as scattered straws.
    // uv = (part, height): part 0 stalk, 1 ear, 2 awns.
    const positions = [];
    const sides = [];
    const uvs = [];
    const indices = [];
    const ribbon = (points) => {
      const first = positions.length / 3;
      for (const { c, s, part } of points) {
        positions.push(c[0], c[1], c[2], c[0], c[1], c[2]);
        sides.push(-s[0], -s[1], -s[2], s[0], s[1], s[2]);
        uvs.push(part, c[1], part, c[1]);
      }
      for (let i = 0; i < points.length - 1; i++) {
        const a = first + i * 2;
        indices.push(a, a + 1, a + 2, a + 2, a + 1, a + 3);
      }
    };
    const STALK_HALF_WIDTH = 0.0022;
    // Ear outline: [fraction of ear length, half width, part]. Spindle-shaped
    // head, then a wider, lighter fan for the awns above it.
    const EAR_PROFILE = [[0, 0.003, 1], [0.15, 0.008, 1], [0.6, 0.0095, 1], [0.9, 0.007, 1], [1, 0.004, 1], [1.5, 0.014, 2]];
    for (let k = 0; k < STALKS_PER_TUFT; k++) {
      const spot = rand() * Math.PI * 2;
      const spread = Math.sqrt(rand()) * 0.11;
      const ox = Math.cos(spot) * spread;
      const oz = Math.sin(spot) * spread;
      const leanDir = rand() * Math.PI * 2;
      const lean = 0.03 + rand() * 0.07; // static outward lean so a tuft fans open
      const lx = Math.cos(leanDir);
      const lz = Math.sin(leanDir);
      const top = 0.86 + rand() * 0.14;
      const earLength = 0.09 + rand() * 0.035;
      const earBase = top - earLength;
      const nod = 0.25 + rand() * 0.35; // ripe heads droop over in the lean direction
      const at = (y, droop) => [ox + lx * (lean * y + droop), y, oz + lz * (lean * y + droop)];
      const facing = rand() * Math.PI;
      const fx = Math.cos(facing);
      const fz = Math.sin(facing);

      const stalk = [];
      for (let i = 0; i <= 3; i++) {
        stalk.push({ c: at(earBase * i / 3, 0), s: [fx * STALK_HALF_WIDTH, 0, fz * STALK_HALF_WIDTH], part: 0 });
      }
      ribbon(stalk);
      // Two crossed planes give the ear volume from any viewing angle.
      for (const [px, pz] of [[fx, fz], [-fz, fx]]) {
        ribbon(EAR_PROFILE.map(([f, w, part]) => ({
          c: at(earBase + f * earLength, nod * f * earLength),
          s: [px * w, 0, pz * w],
          part,
        })));
      }
    }
    const tuft = new BABYLON.Mesh('wheatTuft', scene);
    const vd = new BABYLON.VertexData();
    vd.positions = positions;
    vd.indices = indices;
    vd.uvs = uvs;
    vd.applyToMesh(tuft);
    tuft.setVerticesData('side', sides, false, 3);

    // --- Placement: uniform over the disc at full density out to
    // FULL_RADIUS, then a smooth fade to nothing at FIELD_RADIUS (no visible
    // ring, and the rising canopy surface takes over underneath). Placement
    // order is random, so any prefix of the buffers is an even subsample. ---
    const matrices = new Float32Array(16 * TUFT_COUNT);
    const params = new Float32Array(4 * TUFT_COUNT);
    const tmpMatrix = BABYLON.Matrix.Identity();
    const scale = new BABYLON.Vector3(1, 1, 1);
    const translation = new BABYLON.Vector3(0, 0, 0);
    const density = (r) => {
      if (r < EXCLUDE_RADIUS) return 0;
      if (r < FULL_RADIUS) return 1;
      const t = Math.min(1, (r - FULL_RADIUS) / (FIELD_RADIUS - FULL_RADIUS));
      return 1 - t * t * (3 - 2 * t);
    };
    // Gentle field-scale undulation in crop height, so the canopy top isn't
    // a perfectly flat sheet.
    const swell = (x, z) => 0.6 * Math.sin(x * 0.11 + 1.3) * Math.sin(z * 0.09 + 0.4) + 0.4 * Math.sin((x + z) * 0.23);
    let placed = 0;
    for (let attempts = 0; placed < TUFT_COUNT && attempts < TUFT_COUNT * 4; attempts++) {
      const r = FIELD_RADIUS * Math.sqrt(rand());
      const ang = rand() * Math.PI * 2;
      if (rand() >= density(r)) continue;
      const x = Math.cos(ang) * r;
      const z = Math.sin(ang) * r;
      const height = 0.8 + 0.06 * swell(x, z) + rand() * 0.09; // metres to the ear tips
      scale.set(1, height, 1);
      translation.set(x, 0, z);
      BABYLON.Matrix.ComposeToRef(scale, BABYLON.Quaternion.RotationAxis(BABYLON.Vector3.Up(), rand() * Math.PI * 2), translation, tmpMatrix);
      tmpMatrix.copyToArray(matrices, placed * 16);
      params[placed * 4 + 0] = height;
      params[placed * 4 + 1] = rand() * Math.PI * 2;                 // sway phase
      params[placed * 4 + 2] = rand();                               // straw/gold tint
      params[placed * 4 + 3] = rand() < 0.12 ? 0.5 + rand() * 0.5 : 0; // a few later-ripening, greener plants
      placed++;
    }
    tuft.thinInstanceSetBuffer('matrix', matrices.subarray(0, placed * 16), 16, true);
    tuft.thinInstanceSetBuffer('aParams', params.subarray(0, placed * 4), 4, true);
    tuft.alwaysSelectAsActiveMesh = true;
    this._wheatTuftCount = placed;

    // Wind travel direction: explicit ASSUMPTION authorized for this
    // illustration (wind FROM NW toward SE). In the scene's local XZ axes,
    // "NW -> SE" is approximated as the vector (1, 1) normalized. This is
    // NOT derived from any measured wind direction field (none exists in
    // the telemetry payload).
    const windDir = new BABYLON.Vector2(1, 1).normalize();

    // --- Illustrative gust-band forcing model ---
    // Source: "A Wave-Theoretic Model of Wind-Induced Wheat Field Motion"
    // (Academie royale de Belgique, popups.uliege.be/2593-4228/index.php?id=1986),
    // adopted per explicit direction for the illustrative gust-band look.
    // NOT derived from real measured gust/direction data -- only the overall
    // amplitude SCALE is tied to real wind_speed_mps (via windIntensity).
    //
    // Physical parameters from the paper: stalk length L ~ 1m, tip mass
    // m ~ 0.005 kg, bending stiffness kappa = EI ~ 2e-3 N*m => natural
    // frequency omega0 = sqrt(kappa / (m*L^2)) ~ 2 rad/s (a ~3.1s sway
    // period). Governing PDE is Klein-Gordon; we use only its quasi-static
    // forcing limit, a k^-2-weighted sum of travelling cosines in a narrow
    // cone around the wind direction -- cheap, shader-friendly, and the
    // paper's own simulation approach. Fixed phases + time-only evolution
    // mean the bands genuinely travel across the field.
    const NUM_MODES = 7;
    const OMEGA0 = (2 * Math.PI) / 3.1;
    const WAVE_SPEED = 1.5; // m/s illustrative transverse wave speed (not measured)
    const K_MIN = 0.63; // 1/m, wavelength ~10m
    const K_MAX = 6.28; // 1/m, wavelength ~1m
    const baseAngle = Math.atan2(windDir.y, windDir.x);
    const CONE_HALF_SPREAD = (15 * Math.PI) / 180; // paper's 30deg cone, halved
    let mseed = 20261025;
    const mrand = () => { mseed = (mseed * 1103515245 + 12345) & 0x7fffffff; return (mseed % 1000000) / 1000000; };
    const modeKx = [];
    const modeKz = [];
    const modeOmega = [];
    const modePhase = [];
    const modeAmp = [];
    let ampSum = 0;
    for (let n = 0; n < NUM_MODES; n++) {
      const k = K_MIN * Math.pow(K_MAX / K_MIN, n / (NUM_MODES - 1)); // log-spaced scales
      const theta = baseAngle + (mrand() * 2 - 1) * CONE_HALF_SPREAD;
      modeKx.push(k * Math.cos(theta));
      modeKz.push(k * Math.sin(theta));
      modeOmega.push(Math.sqrt(OMEGA0 * OMEGA0 + WAVE_SPEED * WAVE_SPEED * k * k)); // Klein-Gordon dispersion
      modePhase.push(mrand() * Math.PI * 2);
      const amp = 1 / (k * k); // long wavelengths dominate: legible bands, fine ripple on top
      modeAmp.push(amp);
      ampSum += amp;
    }
    for (let n = 0; n < NUM_MODES; n++) modeAmp[n] /= ampSum;

    const GUST_GLSL = `
      uniform float time;
      uniform float windIntensity;
      uniform float modeKx[7];
      uniform float modeKz[7];
      uniform float modeOmega[7];
      uniform float modePhase[7];
      uniform float modeAmp[7];
      // 0..1 gust strength at a ground position (see the model notes in _buildWheat()).
      float gustAt(vec2 p) {
        float f = 0.0;
        for (int n = 0; n < 7; n++) {
          f += modeAmp[n] * cos(modeKx[n] * p.x + modeKz[n] * p.y - modeOmega[n] * time + modePhase[n]);
        }
        return clamp(0.5 + 0.8 * f, 0.0, 1.0);
      }
    `;
    const FOG_GLSL = `
      uniform vec3 fogColor;
      uniform float fogStart;
      uniform float fogEnd;
      // Matches the scene's linear fog on the standard materials.
      vec3 applyFog(vec3 color, float dist) {
        return mix(fogColor, color, clamp((fogEnd - dist) / (fogEnd - fogStart), 0.0, 1.0));
      }
    `;

    BABYLON.Effect.ShadersStore['wheatVertexShader'] = `
      precision highp float;
      attribute vec3 position;
      attribute vec3 side;
      attribute vec2 uv;
      attribute vec4 world0;
      attribute vec4 world1;
      attribute vec4 world2;
      attribute vec4 world3;
      attribute vec4 aParams;
      uniform mat4 view;
      uniform mat4 projection;
      uniform vec2 windDir;
      uniform vec3 sunDir;
      uniform vec3 cameraPos;
      uniform float pixelScale;
      ${GUST_GLSL}
      varying vec2 vUv;
      varying float vTint;
      varying float vGreen;
      varying float vGust;
      varying float vLight;
      varying float vDist;
      void main() {
        mat4 world = mat4(world0, world1, world2, world3);
        float height = aParams.x;
        vec3 root = world[3].xyz;

        // Widen distant ribbons to ~1.2 px (capped) so the stand reads as
        // continuous coverage rather than sub-pixel sparkle.
        float halfWidth = max(length(side), 1e-4);
        float widen = clamp(0.6 * length(root - cameraPos) * pixelScale / halfWidth, 1.0, 60.0);
        vec3 local = (world * vec4(position + side * widen, 1.0)).xyz - root;

        // Lean angle at the ear tips: a coherent downwind lean that deepens
        // under each passing gust, plus a slow per-tuft sway. Exactly 0 when
        // windIntensity is 0 (calm, stale or reduced motion): upright and still.
        float gust = gustAt(root.xz);
        float theta = windIntensity * (0.18 + 0.75 * gust + 0.06 * sin(time * 2.1 + aParams.y));
        // Bend along a circular arc of the stalk's own length, so heads come
        // down as well as over instead of shearing sideways.
        float phi = theta * local.y / height;
        float along = 0.5 * phi * local.y;
        float up = local.y;
        if (theta > 1e-3) {
          float radius = height / theta;
          along = radius * (1.0 - cos(phi));
          up = radius * sin(phi);
        }
        vec3 dir = vec3(windDir.x, 0.0, windDir.y);
        vec3 worldPos = root + vec3(local.x, 0.0, local.z) + dir * along + vec3(0.0, up, 0.0);

        // Ribbon normal from the bent stalk direction and its width vector,
        // turned to face the camera (ribbons are double-sided).
        vec3 tangent = normalize(dir * sin(phi) + vec3(0.0, cos(phi), 0.0));
        vec3 normal = normalize(cross(tangent, normalize(mat3(world) * side)));
        vec3 toCamera = normalize(cameraPos - worldPos);
        if (dot(normal, toCamera) < 0.0) normal = -normal;
        float diffuse = max(dot(normal, sunDir), 0.0);
        float backlight = pow(max(dot(-toCamera, sunDir), 0.0), 4.0); // translucent glow against the sun
        vLight = 0.75 + 0.6 * diffuse + 0.35 * backlight;

        vUv = uv;
        vTint = aParams.z;
        vGreen = aParams.w;
        vGust = gust;
        vDist = length(worldPos - cameraPos);
        gl_Position = projection * view * vec4(worldPos, 1.0);
      }
    `;
    BABYLON.Effect.ShadersStore['wheatFragmentShader'] = `
      precision highp float;
      uniform float windIntensity;
      ${FOG_GLSL}
      varying vec2 vUv;
      varying float vTint;
      varying float vGreen;
      varying float vGust;
      varying float vLight;
      varying float vDist;
      void main() {
        float part = vUv.x;
        vec3 stalk = mix(vec3(0.62, 0.52, 0.28), vec3(0.84, 0.74, 0.46), vTint);
        vec3 ear = mix(vec3(0.76, 0.56, 0.25), vec3(0.93, 0.74, 0.4), vTint);
        vec3 awn = vec3(0.92, 0.82, 0.56);
        vec3 color = part < 1.0 ? mix(stalk, ear, part) : mix(ear, awn, part - 1.0);
        color = mix(color, vec3(0.6, 0.62, 0.3), vGreen * 0.45);
        // Self-shadowing in a dense stand: deep shade at the base, full light at the ears.
        float ao = mix(0.32, 1.0, smoothstep(0.05, 0.85, vUv.y));
        // Bent-over heads catch more light, so gust waves read as travelling bright bands.
        float sheen = 1.0 + windIntensity * (vGust - 0.5) * 0.45;
        gl_FragColor = vec4(applyFog(color * ao * vLight * sheen, vDist), 1.0);
      }
    `;

    BABYLON.Effect.ShadersStore['wheatCanopyVertexShader'] = `
      precision highp float;
      attribute vec3 position;
      uniform mat4 world;
      uniform mat4 view;
      uniform mat4 projection;
      uniform float canopyStart;
      uniform float canopyEnd;
      uniform float canopyHeight;
      varying vec3 vWorld;
      varying float vRaise;
      void main() {
        vec3 p = (world * vec4(position, 1.0)).xyz;
        vRaise = smoothstep(canopyStart, canopyEnd, length(p.xz));
        p.y += canopyHeight * vRaise;
        vWorld = p;
        gl_Position = projection * view * vec4(p, 1.0);
      }
    `;
    BABYLON.Effect.ShadersStore['wheatCanopyFragmentShader'] = `
      precision highp float;
      uniform vec3 cameraPos;
      ${GUST_GLSL}
      ${FOG_GLSL}
      varying vec3 vWorld;
      varying float vRaise;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
      float noise(vec2 p) {
        vec2 i = floor(p);
        vec2 f = fract(p);
        vec2 u = f * f * (3.0 - 2.0 * f);
        return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
                   mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
      }
      void main() {
        vec2 p = vWorld.xz;
        float dist = length(vWorld - cameraPos);
        // Fine mottling fades out with distance so it never shimmers.
        float fine = 1.0 - smoothstep(30.0, 90.0, dist);
        // Tuft-scale speckle out to mid distance, so the canopy carries the
        // same grain as the instanced stand where the two meet.
        float speckle = 1.0 - smoothstep(90.0, 170.0, dist);
        float n = 0.55 + fine * 0.3 * (noise(p * 1.7) - 0.5) + speckle * 0.35 * (noise(p * 3.1) - 0.5)
          + 0.3 * (noise(p * 0.45) - 0.5) + 0.25 * (noise(p * 0.08) - 0.5);
        vec3 under = vec3(0.4, 0.3, 0.13) * (0.8 + 0.4 * n);                // shade between stalks
        vec3 top = mix(vec3(0.62, 0.47, 0.21), vec3(0.84, 0.68, 0.36), n);    // sunlit crop top
        top *= 1.0 + windIntensity * (gustAt(p) - 0.5) * 0.45;
        gl_FragColor = vec4(applyFog(mix(under, top, vRaise), dist), 1.0);
      }
    `;

    const sunDir = this.sun.direction.scale(-1).normalize();
    const shared = ['view', 'projection', 'time', 'windIntensity', 'cameraPos',
      'modeKx', 'modeKz', 'modeOmega', 'modePhase', 'modeAmp', 'fogColor', 'fogStart', 'fogEnd'];
    const configure = (mat) => {
      mat.setFloat('time', 0);
      mat.setFloat('windIntensity', 0);
      mat.setVector3('cameraPos', this.camera.position);
      // Fixed-once mode arrays: only `time` advances after init.
      mat.setFloats('modeKx', modeKx);
      mat.setFloats('modeKz', modeKz);
      mat.setFloats('modeOmega', modeOmega);
      mat.setFloats('modePhase', modePhase);
      mat.setFloats('modeAmp', modeAmp);
      mat.setColor3('fogColor', scene.fogColor);
      mat.setFloat('fogStart', scene.fogStart);
      mat.setFloat('fogEnd', scene.fogEnd);
      return mat;
    };

    const wheatMat = configure(new BABYLON.ShaderMaterial('wheatMat', scene, { vertex: 'wheat', fragment: 'wheat' }, {
      attributes: ['position', 'side', 'uv', 'world0', 'world1', 'world2', 'world3', 'aParams'],
      uniforms: [...shared, 'windDir', 'sunDir', 'pixelScale'],
      needAlphaBlending: false,
    }));
    wheatMat.backFaceCulling = false;
    wheatMat.setVector2('windDir', windDir);
    wheatMat.setVector3('sunDir', sunDir);
    wheatMat.setFloat('pixelScale', 0.002);
    tuft.material = wheatMat;

    const ground = BABYLON.MeshBuilder.CreateGround('ground', { width: 800, height: 800, subdivisions: 320 }, scene);
    const canopyMat = configure(new BABYLON.ShaderMaterial('wheatCanopyMat', scene, { vertex: 'wheatCanopy', fragment: 'wheatCanopy' }, {
      attributes: ['position'],
      uniforms: [...shared, 'world', 'canopyStart', 'canopyEnd', 'canopyHeight'],
    }));
    canopyMat.setFloat('canopyStart', CANOPY_START);
    canopyMat.setFloat('canopyEnd', CANOPY_END);
    canopyMat.setFloat('canopyHeight', CANOPY_HEIGHT);
    ground.material = canopyMat;

    this.wheatMesh = tuft;
    this.wheatMaterials = [wheatMat, canopyMat];
    this._wheatMaterial = wheatMat;
    this._wheatTime = 0;
    this._wheatFrames = 0;
    this._wheatFrameEma = 1 / MAX_FPS;
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

  /**
   * Fit the camera to the turbine's ACTUAL computed bounding box (tower +
   * nacelle + full swept rotor disc), not a hand-tuned radius constant.
   * This is what the previous implementation got wrong: a fixed radius/fov
   * combination looked fine at one aspect ratio and clipped the rotor at
   * others (mobile portrait). Here we:
   *   1. Read the real world-space bounds of turbineRoot.
   *   2. Always use a fixed VERTICAL fov (simpler to reason about).
   *   3. Solve for the radius required so BOTH the bbox height and the
   *      bbox width (adjusted for aspect) fit within that fov with a
   *      margin, and take the larger (more conservative) of the two.
   * This guarantees >=margin clearance on every edge regardless of
   * viewport aspect ratio, which is verified by the QA bbox-projection
   * script (not just eyeballed).
   */
  _fitCameraToAspect() {
    if (!this.camera || !this.engine || !this.turbineRoot) return;
    const BABYLON = window.BABYLON;
    const w = this.engine.getRenderWidth() || this.canvas.clientWidth || 1;
    const h = this.engine.getRenderHeight() || this.canvas.clientHeight || 1;
    const aspect = w / h;

    // Use the ANALYTIC full swept-rotor disc (hub height +/- rotor radius,
    // at the rotor pivot's z offset), not the instantaneous blade mesh
    // bbox. The mesh bbox only reflects wherever the two blades happen to
    // be sitting right now (e.g. near-vertical at rest), which
    // under-measures the true vertical extent once the rotor is actually
    // spinning and sweeps the full circle -- this was the direct cause of
    // top-edge rotor clipping reported from real screenshots. Tower/base/
    // nacelle still come from the real mesh bbox since those are static.
    const meshBounds = this.turbineRoot.getHierarchyBoundingVectors(true);
    const hubHeight = this.hubHeight || 18;
    const rotorRadius = this.rotorRadius || 6.65;
    const rotorPivotZ = this.rotorPivotZ || 2.3;
    const min = new BABYLON.Vector3(
      Math.min(meshBounds.min.x, -rotorRadius),
      Math.min(meshBounds.min.y, hubHeight - rotorRadius),
      Math.min(meshBounds.min.z, rotorPivotZ - rotorRadius)
    );
    const max = new BABYLON.Vector3(
      Math.max(meshBounds.max.x, rotorRadius),
      Math.max(meshBounds.max.y, hubHeight + rotorRadius),
      Math.max(meshBounds.max.z, rotorPivotZ + rotorRadius)
    );
    const center = min.add(max).scale(0.5);
    const halfHeight = (max.y - min.y) / 2;
    const halfWidth = Math.max(Math.abs(max.x), Math.abs(min.x));

    // Target ~60-70% canvas-height fill (well inside the required 45-85%
    // band with real margin on every edge), not a bare minimum fit. Tuned
    // against the actual projected-bbox QA probe (getProjectedBoundsForQA),
    // not guessed: MARGIN ~1.08 measured ~96% fill in practice (Babylon's
    // vertical-fixed FOV accounts for the full frustum, not just the
    // half-height triangle used in the naive estimate below), so this is
    // deliberately larger than a naive "6% margin" calculation would
    // suggest, to land in-band after the real engine resize/fit pass.
    const MARGIN = 1.55;
    const verticalFov = 0.78; // ~44.7 degrees, fixed regardless of aspect

    // Radius needed so the vertical half-extent fits the vertical fov.
    const radiusForHeight = (halfHeight * MARGIN) / Math.tan(verticalFov / 2);
    // Radius needed so the horizontal half-extent fits the *horizontal*
    // fov implied by this aspect ratio and the same vertical fov.
    const horizontalFov = 2 * Math.atan(Math.tan(verticalFov / 2) * aspect);
    const radiusForWidth = (halfWidth * MARGIN) / Math.tan(horizontalFov / 2);

    const radius = Math.max(radiusForHeight, radiusForWidth, this.camera.lowerRadiusLimit);

    this.camera.fovMode = BABYLON.Camera.FOVMODE_VERTICAL_FIXED;
    this.camera.fov = verticalFov;
    // IMPORTANT: setTarget() must come BEFORE the radius assignment below.
    // ArcRotateCamera.setTarget() recomputes alpha/beta/radius from the
    // camera's current (stale, pre-fit) actual position relative to the
    // new target -- it silently overwrites whatever radius we set earlier
    // in this function with a leftover distance from the camera's old
    // position. This was the real root cause of the top/bottom rotor
    // clipping: the computed fit radius (correctly ~46m once the swept-
    // rotor-disc bbox was fixed) was being clobbered back down to the
    // old, too-close radius by this call ordering bug. Setting the target
    // first, then the radius last, makes the radius assignment authoritative.
    this.camera.setTarget(new BABYLON.Vector3(0, center.y, center.z));
    this.camera.radius = Math.min(radius, this.camera.upperRadiusLimit);

    this._lastFitBounds = { min, max, center, halfHeight, halfWidth, radius: this.camera.radius, aspect };
  }

  /**
   * Loudly verify the camera fit against the FULL SWEPT ROTOR CIRCLE
   * (not instantaneous blade positions), immediately after every
   * _fitCameraToAspect() call. Per explicit review feedback: a silent/
   * non-asserting margin check is as good as no check, since clipping
   * was shipped twice despite "looking fine" in spot-checks. This throws
   * in dev (and always console.errors) so a regression can't pass
   * unnoticed again; callers in production code paths should not let
   * this throw escape uncaught, so _fitCameraToAspect()'s caller wraps
   * construction in the existing top-level try/catch fallback already
   * used for WebGL failures.
   */
  _assertCameraFit() {
    const result = this.getProjectedBoundsForQA();
    if (!result) return null;
    const MIN_FRACTION = 0.45;
    const MAX_FRACTION = 0.85;
    const EDGE_MARGIN_FRACTION = 0.06; // required clearance on every edge
    const { heightFraction, widthFraction, bboxPx, canvasHeight, canvasWidth } = result;
    const topMargin = bboxPx.minY / canvasHeight;
    const bottomMargin = (canvasHeight - bboxPx.maxY) / canvasHeight;
    const leftMargin = bboxPx.minX / canvasWidth;
    const rightMargin = (canvasWidth - bboxPx.maxX) / canvasWidth;
    const problems = [];
    if (heightFraction < MIN_FRACTION || heightFraction > MAX_FRACTION) {
      problems.push(`heightFraction ${heightFraction.toFixed(3)} outside [${MIN_FRACTION}, ${MAX_FRACTION}]`);
    }
    if (topMargin < EDGE_MARGIN_FRACTION) problems.push(`top margin ${topMargin.toFixed(3)} < ${EDGE_MARGIN_FRACTION} (rotor clipped at top)`);
    if (bottomMargin < EDGE_MARGIN_FRACTION) problems.push(`bottom margin ${bottomMargin.toFixed(3)} < ${EDGE_MARGIN_FRACTION}`);
    if (leftMargin < EDGE_MARGIN_FRACTION) problems.push(`left margin ${leftMargin.toFixed(3)} < ${EDGE_MARGIN_FRACTION}`);
    if (rightMargin < EDGE_MARGIN_FRACTION) problems.push(`right margin ${rightMargin.toFixed(3)} < ${EDGE_MARGIN_FRACTION}`);
    const report = { ...result, topMargin, bottomMargin, leftMargin, rightMargin, problems };
    if (problems.length) {
      // eslint-disable-next-line no-console
      console.error('[turbine-scene] camera-fit assertion FAILED:', JSON.stringify(report));
      if (window.__TURBINE_QA_STRICT__) {
        throw new Error(`Camera-fit assertion failed: ${problems.join('; ')}`);
      }
    } else {
      // eslint-disable-next-line no-console
      console.log('[turbine-scene] camera-fit OK:', JSON.stringify(report));
    }
    this._lastFitAssertion = report;
    return report;
  }

  /**
   * QA/debug helper: project the turbine's world bounding box corners to
   * screen space and report the resulting pixel bbox + canvas height
   * fraction, so camera framing can be verified numerically instead of by
   * eyeballing screenshots. Exposed on the instance for exec-driven QA.
   */
  getProjectedBoundsForQA() {
    if (!this.turbineRoot || !this.camera || !this.scene || !this.engine) return null;
    const BABYLON = window.BABYLON;
    const bounds = this.turbineRoot.getHierarchyBoundingVectors(true);
    const w = this.engine.getRenderWidth();
    const h = this.engine.getRenderHeight();
    const viewport = this.camera.viewport.toGlobal(w, h);
    const transform = this.scene.getTransformMatrix();
    const corners = [];
    for (const x of [bounds.min.x, bounds.max.x]) {
      for (const y of [bounds.min.y, bounds.max.y]) {
        for (const z of [bounds.min.z, bounds.max.z]) {
          corners.push(new BABYLON.Vector3(x, y, z));
        }
      }
    }
    let minPx = Infinity, maxPx = -Infinity, minPy = Infinity, maxPy = -Infinity;
    for (const c of corners) {
      const p = BABYLON.Vector3.Project(c, BABYLON.Matrix.Identity(), transform, viewport);
      minPx = Math.min(minPx, p.x);
      maxPx = Math.max(maxPx, p.x);
      minPy = Math.min(minPy, p.y);
      maxPy = Math.max(maxPy, p.y);
    }
    return {
      canvasWidth: w,
      canvasHeight: h,
      bboxPx: { minX: minPx, maxX: maxPx, minY: minPy, maxY: maxPy },
      heightPx: maxPy - minPy,
      heightFraction: (maxPy - minPy) / h,
      widthPx: maxPx - minPx,
      widthFraction: (maxPx - minPx) / w,
    };
  }

  _bindLifecycle() {
    this._onResize = () => {
      if (this.engine) this.engine.resize();
      this._fitCameraToAspect();
    };
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

    // Fix for a real render-path bug (not a capture artifact): the canvas
    // backing buffer defaults to 300x150 until engine.resize() runs, and
    // that call was previously wired only to the window 'resize' event.
    // Any scenario navigation that didn't also trigger a window resize
    // kept the stale 300x150 buffer stretched via CSS to the full layout
    // size -- producing a visibly blurrier render than a page load that
    // happened to coincide with a resize.
    //
    // A single synchronous resize() here is NOT enough: at construction
    // time the host container (e.g. a loading/empty-state wrapper) may
    // still be hidden or unlaid-out, so canvas.clientWidth/Height can be
    // 0 or stale, and resize() silently no-ops against that. Deferring
    // across two animation frames (so at least one real layout+paint
    // pass has happened) makes the first real resize() call land after
    // the canvas has its true on-screen size, regardless of whether a
    // window 'resize' event ever fires afterward.
    const doInitialResize = () => {
      if (this.disposed || !this.engine) return;
      this.engine.resize();
      this._fitCameraToAspect();
    };
    requestAnimationFrame(() => requestAnimationFrame(doInitialResize));
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
    // Wind/grass gating is INDEPENDENT of rotor gating: the rotor only ever
    // reacts to rotor_rpm, the grass only ever reacts to wind_speed_mps.
    // Neither can drive the other's motion.
    const windState = deriveWindState(this._latestStatus, this._latestData, nowWallMs);
    this.lastWindState = windState;

    if (!this.reducedMotion && state.spinning) {
      this._rotorAngle = stepRotorAngle(this._rotorAngle, state.rpm, dtSec);
    }
    // Reduced motion or stopped/stale: rotor angle is simply not advanced
    // (freeze in place), matching the "no fake wobble" requirement.
    if (this.rotorPivot) {
      this.rotorPivot.rotation.z = this._rotorAngle;
    }

    if (this.wheatMaterials) {
      // Reduced motion, or wind telemetry stale/disconnected/invalid: freeze
      // the wheat entirely (don't advance time, force intensity to 0) so a
      // frozen scene never silently keeps "breathing" with stale data.
      const wheatShouldAnimate = !this.reducedMotion && windState.active;
      if (wheatShouldAnimate) {
        this._wheatTime += dtSec;
      }
      for (const mat of this.wheatMaterials) {
        mat.setFloat('time', this._wheatTime);
        mat.setFloat('windIntensity', wheatShouldAnimate ? windState.intensity : 0);
        mat.setVector3('cameraPos', this.camera.position);
      }
      // World size of one pixel per metre of distance, for widening far stalks.
      this._wheatMaterial.setFloat('pixelScale', 2 * Math.tan(this.camera.fov / 2) / this.engine.getRenderHeight());

      // Weak GPUs: if frames persistently can't keep up with MAX_FPS, shed
      // half the tufts (down to a quarter). Placement order is random, so the
      // remaining prefix of the instance buffers is still an even field.
      this._wheatFrameEma = this._wheatFrameEma * 0.95 + Math.min(dtSec, 0.25) * 0.05;
      this._wheatFrames++;
      if (this._wheatFrames > 90 && this._wheatFrameEma > 1.6 / MAX_FPS
          && this.wheatMesh.thinInstanceCount > this._wheatTuftCount / 4) {
        this.wheatMesh.thinInstanceCount = Math.floor(this.wheatMesh.thinInstanceCount / 2);
        this._wheatFrames = 0;
      }
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
