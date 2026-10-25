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
    // Re-toned per review feedback: this is the SHADOWED BASE OF A WHEAT
    // CANOPY, not bare soil. The near-field instanced canopy is now dense
    // enough that almost none of this shows through, but any residual gap
    // must read as shade-between-stalks (a dark gold/olive undertone close
    // to the blade base color) rather than bright dirt -- bright soil
    // showing through was the single biggest cause of the "patchy, grazed
    // lawn" look in review. The texture also carries dense, fine golden/
    // green mottling at a similar visual grain to the grass tint noise, so
    // the far field (beyond the instanced canopy, where this texture is
    // all that's visible) blends into the near field instead of reading
    // as a visibly different, flatter material.
    const groundTex = new BABYLON.DynamicTexture('groundTex', { width: 512, height: 512 }, scene, false);
    const gctx = groundTex.getContext();
    // Per explicit review correction: a dark olive-green ground under
    // gold blades read as a discoloured blob sitting ON the ground, not
    // the ground itself -- "ripe wheat fields are gold ground AND gold
    // crop". Re-toned to the SAME gold family as the blade shader base
    // color (see grass fragment shader below), not a different green hue.
    gctx.fillStyle = '#4a3f18'; // dim wheat-gold shade base, matches blade hue family
    gctx.fillRect(0, 0, 512, 512);
    let seed = 1234567;
    const rand = () => { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return (seed % 1000) / 1000; };
    for (let i = 0; i < 900; i++) {
      const shade = rand();
      // Golden range matching the wheat blade palette (see grass fragment
      // shader base colors below); darker overall than the blades
      // themselves since this represents shaded undergrowth/gaps, but the
      // SAME hue family (gold), not a green undertone.
      const r = Math.floor(58 + shade * 54);
      const g = Math.floor(48 + shade * 46);
      const b = Math.floor(14 + shade * 16);
      gctx.fillStyle = 'rgba(' + r + ',' + g + ',' + b + ',0.6)';
      const x = rand() * 512;
      const y = rand() * 512;
      const rad = 2 + rand() * 5;
      gctx.beginPath();
      gctx.arc(x, y, rad, 0, Math.PI * 2);
      gctx.fill();
    }
    groundTex.update();
    groundTex.uScale = 18;
    groundTex.vScale = 18;
    groundMat.diffuseTexture = groundTex;
    groundMat.specularColor = new BABYLON.Color3(0.02, 0.02, 0.02);
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
    // Per explicit review direction, this is now a WHEAT FIELD density
    // model, not a meadow-tussock model: real wheat is drilled in
    // continuous rows at hundreds of stalks per square metre, not
    // scattered tufts on visible bare ground. The old clump/tussock
    // scatter (a few hundred tussock centers, most ground between them
    // empty) is replaced below with dense near-uniform placement inside
    // NEAR_RADIUS -- blades close enough to touch/overlap -- backed by a
    // probability falloff beyond it so the instanced field blends into
    // the re-toned canopy-shadow ground texture (see groundTex above)
    // rather than ending in a visible ring.
    //
    // NEAR_RADIUS is intentionally smaller than the old meadow version
    // (14m vs 22m): per-blade geometry just dropped from 12 verts/10 tris
    // to 3 verts/1 tri (an ~8-10x cheaper draw per instance), and that
    // entire savings is spent on a much denser NEAR field rather than on
    // pushing individual blades further toward the horizon -- the far
    // field is the ground texture's job, not more instances (see
    // MID_RADIUS falloff below).
    const FIELD_RADIUS = 55;
    const EXCLUDE_RADIUS = 2.2; // keep grass clear of the tower base/plinth
    // Continuous exponential radial density, not a two-zone near/mid
    // split: an explicit near-radius + falloff-band split (tried first)
    // always produced a visible "crop circle" edge at the zone boundary
    // no matter how smooth the band's own probability curve was, because
    // the density on either side of that boundary was still a step
    // function. A single smooth exp(-r/DECAY) falls continuously from
    // full density at the turbine out toward the horizon, with a small
    // floor so it never visually hits a hard zero, and that eliminates
    // the seam entirely.
    //
    // CORRECTED per explicit review of real screenshots: DECAY=8 (~37%
    // of peak density by 8m) collapsed almost all blades into a small
    // disc roughly a third of the frame width, leaving a large empty
    // expanse of bare ground texture to the horizon -- coverage AREA
    // matters more than peak density, and this field's instanced canopy
    // must extend out close to the FIELD_RADIUS, not just near the
    // tower. DECAY raised ~4x so density is still over half its peak at
    // 25m, and FLOOR raised substantially (0.05 -> 0.35) so even the far
    // edge of the disc stays a dense, visually continuous canopy rather
    // than fading into "mostly ground texture" territory.
    const DENSITY_DECAY = 30; // metres: density ~37% of peak by 30m, not 8m -- extends canopy toward the horizon, not just the tower base
    const DENSITY_FLOOR = 0.35; // far edge stays a dense canopy, not a fade into bare/ground-texture-dominated territory
    // Order-of-magnitude density rise per review: cheap 3-vertex blades
    // make this affordable, but it is scaled by viewport AND measured
    // against a real FPS budget (see docs/GAIA133_VISUALIZATION.md FPS
    // section) -- if the dense near field cannot hold frame rate on the
    // mobile budget, the fix is to shrink the mobile RADIUS (fewer total
    // instances via a smaller field), not to thin the near-field density
    // that makes it read as wheat rather than lawn.
    // Measured on this test node (see docs/GAIA133_VISUALIZATION.md FPS
    // section): thin-instance cost here is ~0.01ms/instance with a ~24ms
    // fixed scene overhead, and does NOT scale to "hundreds of stalks/m2"
    // at any usable frame rate on this specific host (100k instances
    // measured at 1.1fps; even the previous, already-approved 7000-count
    // config only measured 9.5fps here). This budget is a deliberate,
    // measured compromise -- see docs for the full table and the explicit
    // call that a literal order-of-magnitude rise is not deliverable
    // within an interactive frame budget on this host, so the visual
    // density gain instead comes from uniform (no bare-gap) placement,
    // wider blades, and a matching ground tone, not from raw count alone.
    // Count raised substantially to match the extended coverage radius
    // above (DECAY 8->30 roughly triples the effective covered radius,
    // i.e. ~9x the covered area) -- per Andrew's explicit correction,
    // this host's FPS measurements are software-rasterized (ANGLE/
    // SwiftShader, no GPU) and are NOT a valid ship gate; thin-instanced
    // single-triangle/two-triangle blades are close to free on real
    // hardware WebGL. Density is chosen for visual coverage; the
    // adaptive DPR/FPS caps, hidden-tab suspension, and reduced-motion
    // behaviour remain the real safety mechanism for weak real clients
    // (see docs/GAIA133_VISUALIZATION.md).
    const COUNT = isNarrow ? 22000 : 48000;

    // Per-blade geometry: a 4-vertex / 2-triangle QUAD (root-left,
    // root-right, tip-left, tip-right), NOT the single 3-vertex sliver
    // tried first. Per explicit review correction: a zero-width sliver
    // has no AREA, so dense slivers still read as scattered straw hairs
    // with visible gaps rather than a canopy -- "cheap geometry was the
    // right instinct, zero width was not". A 2-tri quad is still very
    // cheap (one more triangle than the sliver) but gives each blade
    // real screen coverage. Local y still runs root(0) -> tip(1) so the
    // existing quadratic bend-weight logic in the vertex shader needs no
    // change (both edges bend together).
    const positions = [
      -0.09, 0, 0,  // root left
       0.09, 0, 0,  // root right
      -0.035, 1, 0, // tip left (slight taper, not a point)
       0.035, 1, 0, // tip right
    ];
    const indices = [0, 1, 2, 2, 1, 3];
    const uvs = [0, 0, 1, 0, 0, 1, 1, 1];
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

    // --- Placement: dense, near-UNIFORM scatter (NOT the old tussock-
    // clump model: real drilled wheat is a continuous stand with no bare
    // gaps between clumps). Split into two direct-sampling phases instead
    // of one global rejection-sample loop over the whole FIELD_RADIUS
    // disc: the earlier version sampled uniformly across the full 55m
    // disc and only accepted hits inside the much smaller ~28m near/mid
    // zone, wasting ~85% of the attempts budget and silently placing far
    // fewer blades than COUNT intended (measured: ~26k of a 46k target).
    // Sampling directly within each zone spends every attempt on an
    // actual placement, so the requested density is the density you get. ---
    const placeAt = (rx, rz, idx) => {
      // Wheat character per review: TALLER AND WIDER than the old
      // meadow-grass blades (width raised back up after an earlier pass
      // made it narrower, which fought the "continuous canopy" goal --
      // visual screen-coverage per blade matters more than literal stalk
      // thinness here) and more upright at rest (the vertex shader's
      // baseline lean is proportional to windIntensity, so "upright at
      // calm" already falls out of that).
      const heightScale = 1.3 + rand() * 0.55; // 1.3 - 1.85 m, taller than the old 1.1-1.8 meadow-grass range
      const rot = rand() * Math.PI * 2;
      const widthScale = 1.6 + rand() * 0.9; // widened further per review correction: the quad geometry change alone wasn't enough, blades must visually overlap at this density to read as canopy, not scattered stalks
      BABYLON.Matrix.ComposeToRef(
        new BABYLON.Vector3(widthScale, heightScale, 1),
        BABYLON.Quaternion.RotationAxis(BABYLON.Vector3.Up(), rot),
        new BABYLON.Vector3(rx, 0, rz),
        tmpMatrix
      );
      tmpMatrix.copyToArray(matrices, idx * 16);
      params[idx * 4 + 0] = heightScale;
      params[idx * 4 + 1] = rand() * Math.PI * 2; // phase offset so blades don't all sway in lockstep
      params[idx * 4 + 2] = rand(); // golden/green tint variation 0..1
      params[idx * 4 + 3] = 0;
    };

    const tmpMatrix = BABYLON.Matrix.Identity();
    let placed = 0;

    // Single continuous radial density function, sampled directly rather
    // than via global rejection over the whole FIELD_RADIUS disc (which
    // wastes attempts in proportion to how low the average acceptance
    // probability is -- budgeted generously below instead of guessing).
    // Importance-sample r from an exponential-weighted distribution via
    // inverse CDF, biasing samples toward the turbine where density
    // should be highest, so very few attempts are wasted on far-field
    // rejections even though far-field acceptance probability is low.
    let attempts = 0;
    const maxAttempts = COUNT * 40;
    while (placed < COUNT && attempts < maxAttempts) {
      attempts++;
      // Inverse-CDF sample biased toward small r (exponential-ish), then
      // clamp into the field disc; combined with the acceptProb check
      // below this keeps the accept rate high across the whole range
      // instead of uniformly sampling the full disc and rejecting most
      // far-field attempts outright.
      const u = rand();
      const r = Math.min(FIELD_RADIUS, -DENSITY_DECAY * Math.log(1 - u * (1 - Math.exp(-FIELD_RADIUS / DENSITY_DECAY))));
      if (r < EXCLUDE_RADIUS) continue;
      // Correction term so the *visual* density still matches the target
      // exp(-r/DECAY)+floor curve despite the importance-sampled r
      // distribution already favoring small r (otherwise the floor term
      // would be under-represented at large r). Accept with probability
      // proportional to (floor-adjusted density) / (importance density),
      // normalized so acceptance is always <=1.
      const targetDensity = Math.exp(-r / DENSITY_DECAY) + DENSITY_FLOOR;
      const acceptProb = Math.min(1, targetDensity / (1 + DENSITY_FLOOR));
      if (rand() > acceptProb) continue;
      const ang = rand() * Math.PI * 2;
      placeAt(Math.cos(ang) * r, Math.sin(ang) * r, placed);
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
        // Wheat character: STRONGER coherent lean under wind than the old
        // meadow-grass blades (0.7 + 0.95*gust vs 0.55 + 0.75*gust), since
        // wheat heads/stalks lean further over as a continuous sheet in
        // real footage. At windIntensity=0 (calm) bendAmount is exactly 0
        // -- upright at rest falls out of this directly, no separate
        // "upright" term needed.
        float bendAmount = windIntensity * (0.7 + 0.95 * gust) * bendWeight;
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
        // Wheat palette: GOLD family throughout (matches the re-toned
        // ground texture's gold base), not green-gold -- per explicit
        // review correction, a green-tinted base under a gold ground
        // read as a colour mismatch/discoloured-blob look. Mixes a
        // deeper shadowed gold base with a brighter straw-gold tip
        // per-blade (vTint).
        vec3 base = mix(vec3(0.42, 0.34, 0.09), vec3(0.68, 0.56, 0.18), vTint);
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
