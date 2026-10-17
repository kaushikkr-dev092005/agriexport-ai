/** Pure viewport route math; no scroll-frame DOM measurements. */
export type Point = { x: number; y: number };
export type Box = { x: number; y: number; width: number; height: number };
export const clamp = (v: number, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, v));
export const mix = (a: number, b: number, p: number) => a + (b - a) * p;
export function overlaps(a: Box, b: Box, gap = 9) {
  return a.x < b.x + b.width + gap && a.x + a.width > b.x - gap && a.y < b.y + b.height + gap && a.y + a.height > b.y - gap;
}
export function createRoad(width: number, height: number) {
  const gutter = width < 1024 ? 31 : 47, left = gutter, right = width - gutter;
  const top = Math.max(150, height * .27), bottom = height - 137;
  const nodes = [{ x: left, y: top }, { x: left, y: bottom }, { x: right, y: bottom },
    { x: right, y: top }, { x: left, y: top }, { x: left, y: bottom }];
  const controls = [
    [{ x: left + 13, y: height * .45 }, { x: left - 12, y: bottom - 100 }],
    [{ x: left, y: height - 39 }, { x: right, y: height - 39 }],
    [{ x: right + 12, y: bottom - 100 }, { x: right - 13, y: height * .45 }],
    [{ x: right, y: 105 }, { x: left, y: 105 }],
    [{ x: left + 13, y: height * .45 }, { x: left - 12, y: bottom - 100 }],
  ];
  const d = `M ${nodes[0].x},${nodes[0].y} ` + controls.map(([a, b], i) => `C ${a.x},${a.y} ${b.x},${b.y} ${nodes[i + 1].x},${nodes[i + 1].y}`).join(" ");
  const sample = (phase: number) => {
    const scaled = clamp(phase) * (nodes.length - 1), i = Math.min(controls.length - 1, Math.floor(scaled)), t = scaled - i, u = 1 - t;
    const [a, b] = controls[i], start = nodes[i], end = nodes[i + 1];
    const x = u ** 3 * start.x + 3 * u * u * t * a.x + 3 * u * t * t * b.x + t ** 3 * end.x;
    const y = u ** 3 * start.y + 3 * u * u * t * a.y + 3 * u * t * t * b.y + t ** 3 * end.y;
    const dx = 3 * u * u * (a.x - start.x) + 6 * u * t * (b.x - a.x) + 3 * t * t * (end.x - b.x);
    const dy = 3 * u * u * (a.y - start.y) + 6 * u * t * (b.y - a.y) + 3 * t * t * (end.y - b.y);
    return { x, y, angle: Math.atan2(dy, dx) * 180 / Math.PI };
  };
  return { d, sample };
}
export function routePhase(progress: number, anchors: number[]) {
  for (let i = 0; i < anchors.length - 1; i++) if (progress <= anchors[i + 1]) {
    const local = clamp((progress - anchors[i]) / Math.max(.001, anchors[i + 1] - anchors[i]));
    return (i + local) / (anchors.length - 1);
  }
  return 1;
}
export function sceneLift(progress: number, anchor: number, kind: "export" | "import") {
  const t = clamp((progress - anchor + .045) / .09), eased = t * t * (3 - 2 * t);
  return kind === "export" ? 1 - eased : eased;
}
