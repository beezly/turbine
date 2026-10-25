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
    scene.fogColor = new BABYLON.Color3(0.65, 0.75, 0.85);
    scene.fogStart = 60;
    scene.fogEnd = 220;
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

    // --- Ground: muted, desaturated field with subtle procedural variation
    // (a small dynamic-texture tint, not a flat uniform green) so it reads
    // as a textured field rather than a cartoon plane. ---
    const ground = BABYLON.MeshBuilder.CreateGround('ground', { width: 220, height: 220, subdivisions: 2 }, scene);
    const groundMat = new BABYLON.StandardMaterial('groundMat', scene);
    const groundTex = new BABYLON.DynamicTexture('groundTex', { width: 256, height: 256 }, scene, false);
    const gctx = groundTex.getContext();
    // Base muted olive-green, then a scatter of slightly darker/lighter
    // patches so it is not a single flat color.
    gctx.fillStyle = '#4a5a3c';
    gctx.fillRect(0, 0, 256, 256);
    let seed = 1234567;
    const rand = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return (seed % 1000) / 1000; };
    for (let i = 0; i < 180; i++) {
      const shade = rand();
      const r = Math.floor(58 + shade * 26);
      const g = Math.floor(68 + shade * 26);
      const b = Math.floor(44 + shade * 18);
      gctx.fillStyle = `rgba(${r},${g},${b},0.55)`;
      const x = rand() * 256;
      const y = rand() * 256;
      const rad = 4 + rand() * 10;
      gctx.beginPath();
      gctx.arc(x, y, rad, 0, Math.PI * 2);
      gctx.fill();
    }
    groundTex.update();
    groundTex.uScale = 10;
    groundTex.vScale = 10;
    groundMat.diffuseTexture = groundTex;
    groundMat.specularColor = new BABYLON.Color3(0.03, 0.03, 0.03);
    ground.material = groundMat;
    ground.receiveShadows = true;

    // --- Sky: a vertical gradient (darker/more saturated blue at the
    // zenith fading to a pale, slightly warm horizon) instead of one flat
    // pale-blue band, built with a small dynamic texture (no external
    // image download). ---
    const sky1 = BABYLON.MeshBuilder.CreateSphere('skydome', { diameter: 400, sideOrientation: BABYLON.Mesh.BACKSIDE, segments: 12 }, scene);
    const skyMat = new BABYLON.StandardMaterial('skyMat', scene);
    const skyTex = new BABYLON.DynamicTexture('skyTex', { width: 16, height: 256 }, scene, false);
    const sctx = skyTex.getContext();
    const grad = sctx.createLinearGradient(0, 0, 0, 256);
    grad.addColorStop(0, '#2f5d8f');   // zenith: deeper, more saturated blue
    grad.addColorStop(0.55, '#7fa8cf'); // mid sky
    grad.addColorStop(0.85, '#cfe0ea'); // near horizon: pale, slightly hazy
    grad.addColorStop(1, '#e9ecdf');   // horizon haze, faint warm tint
    sctx.fillStyle = grad;
    sctx.fillRect(0, 0, 16, 256);
    skyTex.update();
    skyMat.diffuseTexture = skyTex;
    skyMat.emissiveTexture = skyTex;
    skyMat.backFaceCulling = false;
    skyMat.disableLighting = true;
    sky1.material = skyMat;
    sky1.infiniteDistance = true;

    this._buildTurbine(shadowGenerator);
    this._buildField(shadowGenerator);
    this._buildGrass();
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

    // Matte materials throughout -- StandardMaterial defaults to a WHITE
    // specular highlight if specularColor isn't set explicitly, which is
    // exactly what made the rocks/trees read as shiny "billiard balls"
    // under the strong directional sun. Every field-prop material below
    // sets specularColor near zero deliberately.
    // Darker, greyer drystone tone -- the previous 0.5/0.46/0.41 pale
    // cream read as breeze-blocks/pallets, not stone. Each segment also
    // gets a small per-segment tint/size jitter below so courses don't
    // look uniformly stamped from one mold.
    const wallMatBase = new BABYLON.Color3(0.32, 0.31, 0.29);

    // Low drystone walls as a chain of short box segments with small real
    // gaps between them (so they read as discrete stacked stone courses,
    // not one continuous plank/rail), each ~1.0-1.2m tall and ~0.45m
    // thick. Two straight runs meeting near the turbine's NW corner (no
    // per-segment rotation jitter -- that fanning was contributing to the
    // "diagonal plank" look).
    // Repositioned using direct camera-projection measurement (not visual
    // guessing) after repeated corner-clipping regressions: in this
    // camera's screen space, DECREASING world x and DECREASING world z
    // both move a point UP and LEFT, away from the bottom-right corner.
    // This run (x -18..-30, z 16) was verified to project with >20%
    // margin on every edge at 1280 width before being committed here.
    const wallSegments = [
      ...Array.from({ length: 4 }, (_, i) => ({ x: -18 - i * 4.0, z: 16, rotY: 0, height: 1.0 + (i % 3) * 0.07 })),
      ...Array.from({ length: 5 }, (_, i) => ({ x: -34, z: 16 - i * 3.6, rotY: Math.PI / 2, height: 1.0 + (i % 3) * 0.07 })),
    ];
    this.wallMeshes = [];
    let wseed = 9173;
    const wrand = () => { wseed = (wseed * 1103515245 + 12345) & 0x7fffffff; return (wseed % 1000) / 1000; };
    wallSegments.forEach((seg, i) => {
      const jitter = (wrand() - 0.5) * 0.06; // +/-0.03 per-channel tonal variation
      const segMat = new BABYLON.StandardMaterial(`wallSegMat${i}`, scene);
      segMat.diffuseColor = new BABYLON.Color3(
        wallMatBase.r + jitter, wallMatBase.g + jitter * 0.9, wallMatBase.b + jitter * 0.8,
      );
      segMat.specularColor = new BABYLON.Color3(0.015, 0.015, 0.015);
      const segWidth = 3.2 + wrand() * 0.6; // slight block-size variation, 3.2-3.8m
      const wall = BABYLON.MeshBuilder.CreateBox('wallSeg', { width: segWidth, height: seg.height, depth: 0.42 + wrand() * 0.06 }, scene);
      wall.position.set(seg.x, seg.height / 2, seg.z);
      wall.rotation.y = seg.rotY;
      wall.material = segMat;
      shadowGenerator.addShadowCaster(wall);
      wall.receiveShadows = true;
      this.wallMeshes.push(wall);
    });

    // The previous tan "scrub patch" ground plane read as a bright flat
    // card dropped on the grass -- too light/saturated against the field,
    // hard polygon edges, and it intruded into frame at every width. Per
    // review direction ("if fiddly, CUT IT -- it adds nothing"), it is
    // removed entirely rather than re-tuned. A small cluster of embedded
    // rocks remains (muted, pulled well clear of the camera frustum edge)
    // as the only eastern-boundary texture cue.
    const rockMat = new BABYLON.StandardMaterial('rockMat', scene);
    rockMat.diffuseColor = new BABYLON.Color3(0.38, 0.37, 0.34);
    rockMat.specularColor = new BABYLON.Color3(0.015, 0.015, 0.015);
    let rseed = 55331;
    const rrand = () => { rseed = (rseed * 1103515245 + 12345) & 0x7fffffff; return (rseed % 1000) / 1000; };
    this.rockMeshes = [];
    for (let i = 0; i < 10; i++) {
      const size = 0.22 + rrand() * 0.4;
      const rock = BABYLON.MeshBuilder.CreatePolyhedron('rock', { type: Math.floor(rrand() * 3), size }, scene);
      // Sink roughly half the rock below the ground plane so it looks
      // embedded rather than resting/floating on top of it. Kept well
      // inside the near field (x 12-18) and south of the tree line so it
      // never approaches the camera frustum edge at 1280/390/320.
      // Verified by direct camera projection (x 4-10, z -3..2) to clear
      // the bottom edge with >10% margin at 1280 width.
      rock.position.set(4 + rrand() * 6, size * 0.35, -3 + rrand() * 5);
      rock.rotation.set(rrand() * Math.PI, rrand() * Math.PI, rrand() * Math.PI);
      rock.material = rockMat;
      shadowGenerator.addShadowCaster(rock);
      this.rockMeshes.push(rock);
    }

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
   * Long meadow-grass field driven by real wind_speed_mps intensity only.
   * Honest limitations (also documented in docs/GAIA133_VISUALIZATION.md):
   *  - The travelling gust/wave PATTERN (which patches bend harder, when,
   *    and the NW->SE travel direction) is a simulated illustrative noise
   *    field, NOT measured local wind direction or gust data.
   *  - Only the overall bend/sway INTENSITY is tied to a real telemetry
   *    value (deriveWindState().intensity, 0..1 from wind_speed_mps).
   *  - No per-blade CPU animation: all deformation happens in a GPU vertex
   *    shader driven by a handful of uniforms updated once per frame;
   *    per-instance variation (height/phase/color) comes from thin-instance
   *    buffers set up once at build time, not touched per frame.
   */
  _buildGrass() {
    const BABYLON = window.BABYLON;
    const scene = this.scene;

    // Mobile/narrow canvases get a smaller density budget. Per explicit
    // feedback from a human review of real screenshots: density without
    // height/clumping just looked like dust/stubble, so height and
    // clumping are prioritized over raw instance count.
    const isNarrow = (this.canvas.clientWidth || window.innerWidth || 1024) < 500;
    // FIELD_RADIUS extended well toward the horizon (was 30m, which left a
    // grassy foreground band then bare ground across the mid/far field in
    // real screenshots). NEAR_RADIUS marks where full density starts
    // thinning; beyond it, placement probability falls off with distance
    // (see acceptProb below) so coverage reads as "grazed-but-grassy" all
    // the way out rather than hard-stopping at a ring.
    const FIELD_RADIUS = 55;
    const NEAR_RADIUS = 22;
    const EXCLUDE_RADIUS = 2.2; // keep grass clear of the tower base/plinth
    const COUNT = isNarrow ? 3400 : 7000; // raised again: previous budget still read as grazed/bare in real screenshots

    // Single tapered blade shape authored with local y in [0, 1] (root to
    // tip). More segments than before so the bend curve (quadratic,
    // weighted toward the tip) reads as a visible arc rather than a stiff
    // leaning stick.
    const positions = [];
    const indices = [];
    const uvs = [];
    const segs = 5;
    for (let i = 0; i <= segs; i++) {
      const t = i / segs;
      const halfW = 0.09 * (1 - t * 0.85) + 0.012; // wide-ish blade, tapers but doesn't vanish to a hairline
      positions.push(-halfW, t, 0, halfW, t, 0);
      uvs.push(0, t, 1, t);
    }
    for (let i = 0; i < segs; i++) {
      const a = i * 2, b = i * 2 + 1, c = i * 2 + 2, d = i * 2 + 3;
      indices.push(a, b, c, b, d, c);
    }
    const bladeMesh = new BABYLON.Mesh('grassBlade', scene);
    const vd = new BABYLON.VertexData();
    vd.positions = positions;
    vd.indices = indices;
    vd.uvs = uvs;
    vd.applyToMesh(bladeMesh);

    // Per-instance buffers: world matrix (position/rotation/scale) plus a
    // custom "aParams" buffer (height scale, phase offset, color tint).
    const matrices = new Float32Array(16 * COUNT);
    const params = new Float32Array(4 * COUNT);
    let seed = 84211;
    const rand = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return (seed % 100000) / 100000; };

    // --- Clumping: scatter a set of tussock centers across the field, then
    // place most blades close to a center (not a uniform peppering), with a
    // cluster-level height/density bias so clumps read as tussocks of
    // varying size, the "long pasture, never a uniform lawn" look. ---
    const NUM_CLUMPS = isNarrow ? 100 : 200; // more tussock centers so near-field density reads as meadow, not scattered tufts
    const clumps = [];
    for (let i = 0; i < NUM_CLUMPS; i++) {
      let cx, cz, dist;
      do {
        cx = (rand() * 2 - 1) * FIELD_RADIUS;
        cz = (rand() * 2 - 1) * FIELD_RADIUS;
        dist = Math.sqrt(cx * cx + cz * cz);
      } while (dist < EXCLUDE_RADIUS + 1.0 || dist > FIELD_RADIUS);
      clumps.push({
        x: cx, z: cz,
        radius: 0.6 + rand() * 1.8,
        heightBias: 0.75 + rand() * 0.6, // some tussocks noticeably taller than others
      });
    }

    let placed = 0;
    let attempts = 0;
    const tmpMatrix = BABYLON.Matrix.Identity();
    while (placed < COUNT && attempts < COUNT * 6) {
      attempts++;
      const clump = clumps[Math.floor(rand() * clumps.length)];
      // Gaussian-ish scatter around the clump center (sum of uniforms),
      // tighter near the middle of the tussock than a flat disc would give.
      const ang = rand() * Math.PI * 2;
      const r = clump.radius * ((rand() + rand()) / 2);
      const rx = clump.x + Math.cos(ang) * r;
      const rz = clump.z + Math.sin(ang) * r;
      const dist = Math.sqrt(rx * rx + rz * rz);
      if (dist < EXCLUDE_RADIUS || dist > FIELD_RADIUS + 3) continue;
      // Thin (don't hard-cut) density with distance beyond NEAR_RADIUS so
      // the field reads as grazed-but-grassy toward the horizon rather
      // than ending in a visible ring of bare ground.
      if (dist > NEAR_RADIUS) {
        const t = Math.min(1, (dist - NEAR_RADIUS) / (FIELD_RADIUS - NEAR_RADIUS));
        const acceptProb = 1 - t * 0.6; // falls to ~40% density at the far edge (raised from 25%), never to 0
        if (rand() > acceptProb) continue;
      }

      // Long meadow grass: 0.9 - 1.5 m tall (raised from an earlier, too-
      // subtle 0.5-0.9m range per direct screenshot review: height, not
      // density, is what makes "long grass" legible at this camera
      // distance), modulated by the clump's own height bias so tussocks
      // vary distinctly from each other.
      const heightScale = (1.1 + rand() * 0.7) * clump.heightBias; // raised again per review: field still read thin/grazed
      const rot = rand() * Math.PI * 2;
      const widthScale = 0.85 + rand() * 0.5;
      BABYLON.Matrix.ComposeToRef(
        new BABYLON.Vector3(widthScale, heightScale, 1),
        BABYLON.Quaternion.RotationAxis(BABYLON.Vector3.Up(), rot),
        new BABYLON.Vector3(rx, 0, rz),
        tmpMatrix
      );
      tmpMatrix.copyToArray(matrices, placed * 16);
      params[placed * 4 + 0] = heightScale;
      params[placed * 4 + 1] = rand() * Math.PI * 2; // phase offset so blades don't all sway in lockstep
      params[placed * 4 + 2] = rand(); // tint variation 0..1
      params[placed * 4 + 3] = 0;
      placed++;
    }

    bladeMesh.thinInstanceSetBuffer('matrix', matrices.subarray(0, placed * 16), 16, true);
    bladeMesh.thinInstanceSetBuffer('aParams', params.subarray(0, placed * 4), 4, true);
    this._grassCount = placed;

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
    // NOT derived from real measured gust/direction data -- see docs for
    // full provenance; only the overall amplitude/frequency SCALE below
    // is tied to real wind_speed_mps (via windIntensity, applied in the
    // shader, not here).
    //
    // Physical parameters from the paper, mapped onto our ~1-1.5m blades:
    //   stalk length L ~ 1m, tip mass m ~ 0.005 kg, bending stiffness
    //   kappa = EI ~ 2e-3 N*m (E~5GPa, outer diameter 5mm, wall 0.5mm)
    //   => natural frequency omega0 = sqrt(kappa / (m*L^2)) ~ 2 rad/s,
    //      i.e. a ~3.1s fundamental sway period -- used directly below.
    // Governing PDE is Klein-Gordon (d2z/dt2 = v^2*lap(z) - omega0^2*z +
    // f/m); we do NOT implement the PDE, only its quasi-static forcing
    // limit (z ~= f/(m*omega0^2)), i.e. a weighted sum of cosines -- cheap
    // and shader-friendly, matching the paper's own simulation approach.
    const NUM_MODES = 7;
    const OMEGA0 = (2 * Math.PI) / 3.1; // ~2.03 rad/s, paper's natural frequency
    const WAVE_SPEED = 1.5; // m/s illustrative transverse wave speed (not measured)
    const K_MIN = 0.63; // 1/m, wavelength ~10m
    const K_MAX = 6.28; // 1/m, wavelength ~1m
    const baseAngle = Math.atan2(windDir.y, windDir.x); // NW->SE direction
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
      // Log-spaced magnitudes so both broad metre-scale swells and finer
      // ripples are represented, not just a cluster at one scale.
      const t = n / (NUM_MODES - 1);
      const k = K_MIN * Math.pow(K_MAX / K_MIN, t);
      const theta = baseAngle + (mrand() * 2 - 1) * CONE_HALF_SPREAD;
      modeKx.push(k * Math.cos(theta));
      modeKz.push(k * Math.sin(theta));
      // Klein-Gordon dispersion: a gapped, quadratic branch -- nothing
      // moves slower than omega0, longer waves are slower.
      modeOmega.push(Math.sqrt(OMEGA0 * OMEGA0 + WAVE_SPEED * WAVE_SPEED * k * k));
      // Fixed once at init, never re-randomized per frame -- time enters
      // only through omega_n*t, giving coherent, repeatable travel.
      modePhase.push(mrand() * Math.PI * 2);
      // A_n proportional to k_n^-2: long wavelengths dominate, short ones
      // are fine texture on top. This is the detail that turns uniform
      // dust into legible travelling gust bands.
      const amp = 1 / (k * k);
      modeAmp.push(amp);
      ampSum += amp;
    }
    // Normalize so the summed field is O(1) regardless of NUM_MODES/K
    // range choices, before the shader applies the real windIntensity and
    // tip-displacement scale on top.
    for (let n = 0; n < NUM_MODES; n++) modeAmp[n] /= ampSum;

    BABYLON.Effect.ShadersStore['grassVertexShader'] = `
      precision highp float;
      attribute vec3 position;
      attribute vec2 uv;
      attribute vec4 world0;
      attribute vec4 world1;
      attribute vec4 world2;
      attribute vec4 world3;
      attribute vec4 aParams;
      uniform mat4 view;
      uniform mat4 projection;
      uniform float time;
      uniform float windIntensity;
      uniform vec2 windDir;
      uniform float modeKx[7];
      uniform float modeKz[7];
      uniform float modeOmega[7];
      uniform float modePhase[7];
      uniform float modeAmp[7];
      varying vec2 vUv;
      varying float vTint;
      varying float vPatch;
      void main() {
        mat4 world = mat4(world0, world1, world2, world3);
        float phase = aParams.y;
        vTint = aParams.z;
        vec3 worldRoot = (world * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
        // Illustrative travelling gust-band forcing: quasi-static limit of
        // a Klein-Gordon stalk model (see _buildGrass() comment + docs for
        // the paper and parameters), a k^-2-weighted sum of fixed-phase
        // cosine modes in a narrow NW->SE cone. NOT real gust/direction
        // data -- only the overall bend/sway INTENSITY multiplier
        // (windIntensity) is tied to real wind_speed_mps telemetry. Fixed
        // phases + time-only evolution means the pattern genuinely
        // translates across the field rather than jittering stochastically.
        float f = 0.0;
        for (int n = 0; n < 7; n++) {
          float kdotx = modeKx[n] * worldRoot.x + modeKz[n] * worldRoot.z;
          f += modeAmp[n] * cos(kdotx - modeOmega[n] * time + modePhase[n]);
        }
        float gust = clamp(0.5 + 0.5 * f, 0.0, 1.0);
        vPatch = gust;
        float bendWeight = position.y * position.y; // quadratic: mostly bends near the tip
        // Baseline lean (not just gust-modulated) so the field reads as
        // "bent over" at real wind speed, not "near-upright with flecks":
        // at windIntensity=1 the tip offset is a large fraction of blade
        // height, i.e. a pronounced lean, matching the "bent over markedly"
        // requirement.
        float bendAmount = windIntensity * (0.55 + 0.75 * gust) * bendWeight;
        float microSway = windIntensity * 0.08 * sin(time * 4.2 + phase) * bendWeight;
        vec3 localPos = position;
        localPos.x += (windDir.x * bendAmount + microSway);
        localPos.z += (windDir.y * bendAmount + microSway);
        vec4 worldPos = world * vec4(localPos, 1.0);
        gl_Position = projection * view * worldPos;
        vUv = uv;
      }
    `;
    BABYLON.Effect.ShadersStore['grassFragmentShader'] = `
      precision highp float;
      varying vec2 vUv;
      varying float vTint;
      varying float vPatch;
      void main() {
        vec3 base = mix(vec3(0.24, 0.32, 0.12), vec3(0.4, 0.48, 0.19), vTint);
        // Coherent lighter/darker travelling patches (vPatch, shared by the
        // whole gust wave, not per-blade random noise) so a single still
        // shows legible gust bands, plus a per-blade tip highlight.
        vec3 patchShaded = base * (0.78 + 0.4 * vPatch);
        vec3 color = mix(patchShaded, patchShaded * 1.18 + vec3(0.03, 0.04, 0.0), vUv.y);
        gl_FragColor = vec4(color, 1.0);
      }
    `;
    const grassMat = new BABYLON.ShaderMaterial('grassMat', scene, { vertex: 'grass', fragment: 'grass' }, {
      attributes: ['position', 'uv', 'world0', 'world1', 'world2', 'world3', 'aParams'],
      uniforms: [
        'view', 'projection', 'time', 'windIntensity', 'windDir',
        'modeKx', 'modeKz', 'modeOmega', 'modePhase', 'modeAmp',
      ],
      needAlphaBlending: false,
    });
    grassMat.backFaceCulling = false;
    grassMat.setVector2('windDir', windDir);
    grassMat.setFloat('time', 0);
    grassMat.setFloat('windIntensity', 0);
    // Fixed-once mode arrays for the gust-band forcing model (see comment
    // block above): these never change after init, only `time` advances.
    grassMat.setFloats('modeKx', modeKx);
    grassMat.setFloats('modeKz', modeKz);
    grassMat.setFloats('modeOmega', modeOmega);
    grassMat.setFloats('modePhase', modePhase);
    grassMat.setFloats('modeAmp', modeAmp);
    bladeMesh.material = grassMat;
    bladeMesh.alwaysSelectAsActiveMesh = true;

    this.grassMesh = bladeMesh;
    this.grassMaterial = grassMat;
    this._grassTime = 0;
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

    if (this.grassMaterial) {
      // Reduced motion, or wind telemetry stale/disconnected/invalid: freeze
      // the grass entirely (don't advance time, force intensity to 0) so a
      // frozen scene never silently keeps "breathing" with stale data.
      const grassShouldAnimate = !this.reducedMotion && windState.active;
      if (grassShouldAnimate) {
        this._grassTime += dtSec;
      }
      this.grassMaterial.setFloat('time', this._grassTime);
      this.grassMaterial.setFloat('windIntensity', grassShouldAnimate ? windState.intensity : 0);
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
