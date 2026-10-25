# Turbine Dashboard UI Redesign Specification

> **⚠️ NOTE (2026-10-25):** The numbers in this spec are *targets*, not results; none have been measured. The "Optional 3D Turbine View (Babylon.js)" requirement was evaluated and declined — see `docs/BABYLONJS_DECISION.md`. The "offline preview with mock telemetry fixture" requirement is met by `tools/preview_server.py`, which labels fixtures and never touches hardware. The spec's own rule "no fabricated LIVE data" was violated by the original mock mode; that mode has been removed.


## Requirements

### 1. Visual Layout Improvements
- Responsive grid-based layout (3-4 columns on desktop, 1-2 on tablet, 1 on mobile)
- Hierarchical metric display: Critical metrics large at top, operational details below
- Better visual grouping: Power/Rotation/Voltage in distinct card sections
- Improved contrast for accessibility (WCAG AA minimum)

### 2. State Indicators
- Connected: Green glow, bright indicator
- Stale: Yellow/amber, dimmed metric values, "stale data" badge
- Loading: Blue spinner/pulse, skeleton text
- Unavailable: Red/rose, grayed out, "N/A" display

### 3. Mobile & Keyboard Optimization  
- Touch-friendly buttons (min 48px/44px), adequate spacing
- Keyboard navigation: Tab through controls in logical order
- Focus indicators: Clear blue ring around focused elements
- Portrait/landscape mode support

### 4. Optional 3D Turbine View (Babylon.js)
- Lightweight 3D model of turbine rotor
- Driven by actual rotor RPM data
- Non-critical: LazyLoad with graceful fallback
- WebGL unavailable: Display static SVG/image instead
- Reduced motion support: Disable rotation animation if prefers-reduced-motion

### 5. Performance & Accessibility
- Lazy load 3D library only if requested/visible
- Fallback HTML for WebGL failures
- Reduced motion: Respect prefers-reduced-motion media query
- Render pause when hidden (visibility API)
- Pixel ratio cap: devicePixelRatio capped at 2 for mobile

### 6. Data & Controls
- No fabricated LIVE data in static mock (clear demo fixture label)
- Backend command/auth semantics unchanged
- Frontend-only files/tests/docs
- Offline preview with mock telemetry fixture

## Architecture

### Directory Structure
```
turbine/
├── templates/
│   ├── index.html              (main template, responsive)
│   └── components.html         (optional partials if needed)
├── static/                     (new directory)
│   ├── css/
│   │   ├── main.css           (layout, typography)
│   │   ├── states.css         (status indicators, states)
│   │   ├── responsive.css     (media queries)
│   │   └── 3d.css             (3D view styles, lazy-loaded)
│   ├── js/
│   │   ├── app.js             (main logic, socket.io)
│   │   ├── states.js          (state management)
│   │   ├── turbine3d.js       (lazy-loaded 3D module)
│   │   └── mock-data.js       (offline demo fixture)
│   ├── models/
│   │   └── turbine.glb        (3D model, if included)
│   └── assets/
│       ├── icons/
│       └── placeholders/
└── tests/
    ├── frontend_qa_suite.py    (automation/screenshot tests)
    └── mock_backend.py         (local mock server)
```

### CSS Variables (Dark Theme, Accessible)
```css
:root {
  /* States */
  --state-connected: #34d399;    (emerald, bright)
  --state-stale: #fbbf24;        (amber, warning)
  --state-loading: #38bdf8;      (cyan, info)
  --state-unavailable: #fb7185;  (rose, error)
  
  /* Contrast */
  --text-high: #f1f5f9;   (min 7:1 on dark bg)
  --text-mid: #cbd5e1;    (min 4.5:1)
  --text-low: #94a3b8;    (secondary)
  
  /* Reduced Motion */
  @media (prefers-reduced-motion: reduce) {
    --transition: none;
    --animation: none;
  }
}
```

## Implementation Checklist

- [ ] Create responsive layout (12-col grid on desktop, fluid mobile)
- [ ] Add state indicator system (CSS classes: .state-connected, .state-stale, etc)
- [ ] Implement keyboard navigation (tabindex, focus styles)
- [ ] Add mobile touch targets (min 48x48px)
- [ ] Create 3D turbine component (lazy-loaded Babylon.js module)
- [ ] Add WebGL fallback (SVG/PNG static image)
- [ ] Test reduced-motion support
- [ ] Create offline mock telemetry (demo fixture, clearly labeled)
- [ ] Add responsive screenshots and QA verification
- [ ] Document deployment & testing procedures

## Browser Support
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
- Mobile Safari (iOS 14+)
- Android Chrome

## Performance Targets (targets only — none measured)
- First paint: < 1.5s (with mock data)
- 3D model load: < 2s (lazy, async)
- TTI (Time to Interactive): < 2.5s
- Lighthouse score: 90+ (Performance, Accessibility, Best Practices)

---

## Correction Note (2026-10-25)

This spec contains targets, not measurements, and none of the targets (first paint, TTI, 3D load time,
Lighthouse 90+) have been measured. The measured and corrected figures for the implementation that followed
(and the list of unverified claims made in the companion documents) are in the Correction Notes at the end of
`UI_REDESIGN_REPORT.md` and `COMPLETION_SUMMARY.md`. Outcome of requirement 4 (optional 3D view): declined,
see `docs/BABYLONJS_DECISION.md`.
