# Truck guide assets

No final image assets have been supplied. The current original SVG silhouettes are explicitly labelled TODO placeholders. No reference images or third-party artwork are included.

Add licensed transparent cutouts here, then restart development or rebuild:

- `truck.webp`: right-facing side view, bare trailer bed, 160:82 aspect ratio. Keep the exhaust near (121,20) in that coordinate system; adjust `GUIDE_SETTINGS.exhaustOffset` if needed.
- `container.webp`: approximately 96:40, transparent background.
- `crane.webp`: approximately square, transparent background; position the hoist near the center. A baked-in cable cannot scrub independently; supply a cable-free cutout for the SVG cable upgrade.

`scripts/sync-guide-assets.mjs` updates `assets.json` before build/dev. Missing files are never requested. Images have explicit dimensions, lazy loading, async decoding, and an error fallback. Placeholder wheels rotate; a single final truck image has no independently rotating wheel layers. Supply separate layers for that refinement. The rendering boundary is `TruckSprite.tsx`; WebGL/GLB support has not been built.
