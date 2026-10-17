# Landing page truck guide

The guide progressively enhances the existing Next.js landing page only. It uses the existing Motion package, landing CSS variables and fonts. No runtime library was added. ESLint, its JS configuration and TypeScript ESLint were added as development checks; `npm run lint` checks the new guide and asset-sync script, not the entire historical codebase.

## Edit points

- `apps/dashboard/components/guide/guideStops.ts`: all six stops, copy, section selectors, link targets, smoke limits, exhaust offset and sizes.
- `mockData.ts`: all illustrative card values. Every card displays **Sample data**; none is a market signal.
- `geometry.ts`: viewport route, section-to-route interpolation and reversible container lift math.
- `guide.css`: styles inherit the real `--land-*` tokens. Glass radius is 24px.
- `public/guide/README.md`: final asset contract and remaining asset TODOs.

Only `/` and `/dashboard` exist. Export deals currently open `/dashboard`; import deals open `/dashboard#evidence`. Both show explicit route-pending notes. TODO comments identify where to replace these fallbacks when real deal pages exist. The approach and FAQ stops use real section anchors. Ordinary footer shortcuts duplicate every guide link, so navigation never depends on the overlay.

## Behavior and accessibility

Motion scroll values feed an event-woken rAF smoother. Section detection uses IntersectionObserver. Text/hit-area rectangles are cached on resize/content changes; scroll frames do no layout measurements. Truck motion, bob, wheel rotation, cards and lift scenes animate transforms/opacity. The road is clipped to the perimeter and masks text/control rectangles. Desktop cards seek empty space; if none exists they defer to the Stop details control instead of covering content. Ambient cards are decorative and omitted where space is unsafe. The truck temporarily fades where a route segment would overlap content.

At mobile widths the truck is docked at the edge and the **Guide** control opens a dismissible bottom sheet on request. It does not automatically cover content. Tablet uses a smaller truck and perimeter route; constrained stop cards can be read through Stop details. All overlay graphics are hidden from screen readers. Buttons and links have accessible names and visible keyboard focus. The guide suspends while the existing mobile navigation is open. Hide/show is persisted in localStorage with storage-denial handling.

Reduced motion mounts only a static truck and a Next stops link to the ordinary six-link footer list: no scroll-driving hook, road or smoke. The canvas caps live particles at 60 desktop/tablet and 12 mobile, stops emission after 2.2 seconds without input and drains remaining puffs within another two seconds. Hidden-tab/off-screen suspension clears the canvas. A cached radial texture avoids per-frame gradient creation. There is no continuous idle animation frame loop once scrolling/smoke settle. Target highlight pulses only at active stops.

## Run and verify

From `apps/dashboard` with Node 22 on PATH:

```powershell
npm install
npm run dev -- --port 3000
npm run lint
npm run typecheck
npx playwright test --config playwright.guide.config.ts
```

The focused guide configuration starts/reuses port 3100 and requires Microsoft Edge. The full production browser suite uses isolated API/Next servers on 8123/3123:

```powershell
npm run build
npm run test:e2e
```

Checks cover deterministic/reversible geometry, six stop targets and fallback URLs, container movement, bounded/draining smoke, widths 375/768/1440, original CTA clickability, hide persistence, keyboard activation, denied storage, reduced motion, landing-only mounting and browser errors. Screenshots go to `data/screenshots`. Performance is structurally bounded; a browser pass on this workstation does not certify 60fps on a mid-range laptop. Final asset lighting/realism remains unverified until cutouts are provided.
