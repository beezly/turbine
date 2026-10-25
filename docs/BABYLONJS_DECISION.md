# Decision: no Babylon.js 3D rotor view

**Date:** 2026-10-25
**Status:** Declined (option b). Revisit only if a real 3D asset and a vendoring/build step appear.

## What was asked

`UI_REDESIGN_SPEC.md` listed an "Optional 3D Turbine View (Babylon.js)": lazy-loaded, driven by real RPM
telemetry, with a no-WebGL fallback, `prefers-reduced-motion` support, pause-when-hidden and a capped pixel
ratio. The served page is `templates/index.html`; the RPM fields it receives are `rotor_rpm` and
`generator_rpm` (the spec's "rotor_revs / gen_revs" are the controller data IDs behind them).

## Evidence gathered

Sizes were measured on 2026-10-25 with `curl` (bytes on the wire for the request shown):

| Resource | Bytes | Notes |
|---|---|---|
| `https://cdn.babylonjs.com/babylon.js` | 8,745,275 | server returned the same size with `Accept-Encoding: gzip`, i.e. no compression observed |
| `https://cdnjs.cloudflare.com/ajax/libs/babylonjs/7.0.0/babylon.min.js` | 4,997,079 raw / 1,096,006 gzip | |
| `socket.io 4.0.1` (already used by the page) | 185,009 raw / 36,623 gzip | |
| current `templates/index.html` | 63,223 raw / 11,729 gzip | whole page, inline CSS + JS |

So the smallest Babylon option measured is about 1.1 MB gzipped (5 MB parsed JS), roughly 93x the gzipped size
of the entire current page, to draw a three-bladed rotor.

From the Babylon.js documentation (retrieved via Context7 from doc.babylonjs.com):

- The UMD/CDN build is not tree-shakeable: "your bundled JavaScript file will typically be at least the size of the
  minified Babylon.js library" unless you make a custom build.
- Tree-shaking only works with the ES6 `@babylonjs/core` packages plus a bundler (Webpack/Vite/Rollup/esbuild).
  This project has no JavaScript build step: it is one Flask template with inline script.
- The CDN script tags are described as intended for "learning and experiments, not production environments".
- Babylon Lite (smaller) is described as WebGPU-exclusive, which excludes a lot of the browsers and kiosks that
  would plausibly show a turbine dashboard.

## Reasoning

1. **Value is small.** The information is two numbers (rotor and generator RPM) which the page already shows as
   large readouts. A 3D rotor adds no information, and there is no turbine model asset in the repository; it would
   be hand-built primitives.
2. **Cost is large and lands on the wrong side.** The dashboard is served by a small device on a LAN. The page
   already depends on cdnjs for socket.io (a weakness when the LAN has no internet). Adding a 1-5 MB third-party
   script worsens exactly the offline case; vendoring it would put a multi-megabyte minified file into the repo.
3. **Integrity and supply chain.** A CDN script on a page that can send turbine control commands should carry
   Subresource Integrity and a pinned version. That is more moving parts to maintain than the feature is worth.
4. **Honesty risk.** A rotor animation that keeps spinning after data goes stale, or that is speed-scaled
   inaccurately, is the same class of problem as the removed mock mode: a graphic implying the turbine is doing
   something the telemetry does not support. A 3D scene needs freeze-on-stale, no-WebGL and reduced-motion
   handling to be correct, which is more surface to get wrong than a number.
5. **Maintenance.** Babylon major versions change APIs; nobody on this project owns 3D rendering.

## What to do instead (not implemented here)

If a visual is wanted, a small inline SVG rotor (about 1 KB, no dependency) driven by `rotor_rpm`, frozen when the
page is in a stale/disconnected state and not animated under `prefers-reduced-motion`, covers the use case. Not
built as part of this change.

Related existing issue worth fixing separately: the header turbine icon in `templates/index.html`
(`.turbine-icon svg`) spins at a constant 8 s per revolution regardless of telemetry, so it signals "rotating" even when
the turbine is stopped or the data is stale.

## Not verified

- The Babylon sizes above were measured from the CDNs on one day; versions change.
- Nothing was tested in a browser: no prototype was built, because the decision was to decline.
