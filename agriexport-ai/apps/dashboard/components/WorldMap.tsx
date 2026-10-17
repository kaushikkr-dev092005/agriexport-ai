"use client";
import { useEffect, useState } from "react";
type Polygon = number[][][];
type Feature = { properties: { ISO_N3: string; NAME: string }; geometry: { type: string; coordinates: Polygon | Polygon[] } };
function shape(feature: Feature) {
  const polygons = feature.geometry.type === "Polygon" ? [feature.geometry.coordinates as Polygon] : feature.geometry.coordinates as Polygon[];
  return polygons.map(p => p.map(r => r.map(([lon, lat], i) => `${i ? "L" : "M"}${((lon + 180) * 2).toFixed(2)},${((90 - lat) * 2).toFixed(2)}`).join(" ") + "Z").join(" ")).join(" ");
}
export default function WorldMap({ selected, countries, onSelect }: { selected: string; countries: { country_code: string; name: string }[]; onSelect: (code: string) => void }) {
  const [features, setFeatures] = useState<Feature[]>([]), [failed, setFailed] = useState(false);
  useEffect(() => { const abort = new AbortController(); fetch("/world.geojson", { signal: abort.signal }).then(r => { if (!r.ok) throw Error(); return r.json(); }).then(data => setFeatures(data.features)).catch(() => { if (!abort.signal.aborted) setFailed(true); }); return () => abort.abort(); }, []);
  return <div className="world-map">{failed ? <p>Reference map unavailable. Use the market selector above.</p> : <svg role="img" aria-label="Reference world map. Select a supported market using the map or the accessible market selector." viewBox="0 18 720 300">{features.map((f, i) => { const code = String(f.properties.ISO_N3); const supported = countries.some(c => c.country_code === code); return <path key={i} d={shape(f)} fill={code === selected ? "#267a61" : supported ? "#9dc8b9" : "#e7ece8"} stroke="#fff" strokeWidth=".65" style={{ cursor: supported ? "pointer" : "default" }} onClick={() => supported && onSelect(code)}><title>{f.properties.NAME}{code === selected ? " · selected market" : supported ? " · reference available" : " · coverage unverified"}</title></path>; })}</svg>}<p>Reference geography: Natural Earth, public domain. Boundaries do not imply market eligibility.</p></div>;
}
