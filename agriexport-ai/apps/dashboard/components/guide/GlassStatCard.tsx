import { GUIDE_SAMPLE_DATA as samples } from "./mockData";

/** Decorative sample figures, deliberately not presented as live exporter statistics. */
export function GlassStatCard({ variant }: { variant: "growth" | "shipments" }) {
  const points = samples.growth.points.map((value, i) => `${8 + i * 26},${64 - value * 1.5}`).join(" ");
  const index = samples.growth.highlightedIndex;
  return <div className="guide-glass-stat" aria-hidden="true" data-sample-data="true"><span className="guide-sample-tag">{samples.label}</span>
    {variant === "growth" ? <><span>{samples.growth.title}</span><strong>{samples.growth.value}</strong><svg viewBox="0 0 150 70"><polyline points={points} fill="none" className="guide-chart-line" /><circle cx={8 + index * 26} cy={64 - samples.growth.points[index] * 1.5} r="4" /></svg></> : <><span>{samples.shipments.title}</span><strong>{samples.shipments.percentage}%</strong><div className="guide-sample-segments">{Array.from({ length: samples.shipments.segments }, (_, i) => <i key={i} className={i < Math.round(samples.shipments.percentage / 10) ? "filled" : ""} />)}</div></>}
    <small>Illustration only · not market evidence</small>
  </div>;
}
