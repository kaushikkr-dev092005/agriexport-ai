"use client";
import { useState, type ReactNode } from "react";
import { motion, type MotionValue } from "motion/react";
import { GUIDE_SETTINGS } from "./guideStops";
import assets from "@/public/guide/assets.json";

/** Asset boundary: a future WebP/PNG or optional GLB can replace this renderer alone. */
export function TruckSprite({ wheelAngle, bob, children, compact = false }: { wheelAngle: MotionValue<number>; bob: MotionValue<number>; children?: ReactNode; compact?: boolean }) {
  const [assetAvailable, setAssetAvailable] = useState(assets.truck);
  return <div className={`guide-truck-sprite ${compact ? "compact" : ""}`} aria-hidden="true">
    <motion.div style={{ y: bob }} className="guide-truck-body">
      {assetAvailable && <img src={GUIDE_SETTINGS.assets.truck} width="160" height="82" loading="lazy" decoding="async" onError={() => setAssetAvailable(false)} alt="" className="guide-truck-asset" />}
      {!assetAvailable && <svg viewBox="0 0 160 82" className="guide-truck-placeholder"><title>Truck silhouette placeholder</title><path d="M9 53h97V39h22l13 12 9 3v13H9z" className="truck-bed" /><path d="M104 26h24l15 24v16h-39z" className="truck-cab" /><path d="M113 31h12l9 17h-21z" className="truck-window" /><path d="M104 53h36M111 56v5M18 50h80M7 67h145" className="truck-details" /><rect x="144" y="55" width="7" height="5" rx="1" className="truck-lamp" /><path d="M120 27V17h5" className="truck-exhaust" />{[29, 48, 126].map(x => <g key={x} transform={`translate(${x} 67)`}><circle r="10" className="truck-tire" /><motion.g style={{ rotate: wheelAngle }}><circle r="5.6" className="truck-hub" /><path d="M-5 0h10M0-5v10" className="truck-spokes" /></motion.g></g>)}</svg>}
      {children}
    </motion.div>
    {!assetAvailable && <span className="guide-asset-todo">TODO: final truck asset</span>}
  </div>;
}
