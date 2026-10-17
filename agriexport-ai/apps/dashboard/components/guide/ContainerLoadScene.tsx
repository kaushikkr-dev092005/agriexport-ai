"use client";
import { useState, type RefObject } from "react";
import { motion, useTransform, type MotionValue } from "motion/react";
import assets from "@/public/guide/assets.json";
import { GUIDE_SETTINGS } from "./guideStops";
import { clamp, sceneLift } from "./geometry";

/** Container and rope positions are pure scroll functions, including reverse scrubbing. */
export function ContainerLoadScene({ progress, anchors, scale }: { progress: MotionValue<number>; anchors: RefObject<number[]>; scale: number }) {
  const [containerAsset, setContainerAsset] = useState(assets.container), [craneAsset, setCraneAsset] = useState(assets.crane);
  const lift = useTransform(progress, p => p < anchors.current[4] - .045 ? sceneLift(p, anchors.current[3], "export") : sceneLift(p, anchors.current[4], "import"));
  const y = useTransform(lift, n => -84 * scale * n);
  const containerOpacity = useTransform(progress, p => clamp((p - anchors.current[3] + .06) / .015) * clamp((anchors.current[4] + .06 - p) / .015));
  const craneOpacity = useTransform(progress, p => Math.max(clamp(1 - Math.abs(p - anchors.current[3]) / .07), clamp(1 - Math.abs(p - anchors.current[4]) / .07)));
  const ropeScale = useTransform(lift, n => .19 + .75 * (1 - n));
  return <div className="guide-container-scene" aria-hidden="true">
    <motion.div className="guide-crane" style={{ opacity: craneOpacity }}>
      {craneAsset ? <img src={GUIDE_SETTINGS.assets.crane} width="160" height="160" loading="lazy" decoding="async" alt="" onError={() => setCraneAsset(false)} /> : <svg viewBox="0 0 160 160"><path d="M13 128V19h89M6 129h25M13 23l63 1M13 23l47 24M14 48h48M14 76h27" className="guide-crane-frame" /><motion.g style={{ scaleY: ropeScale, transformOrigin: "77px 23px" }}><path d="M77 23v95" className="guide-crane-rope" /></motion.g></svg>}
      {!craneAsset && <span className="guide-crane-todo">TODO: crane</span>}
    </motion.div>
    <motion.div className="guide-container" style={{ y, opacity: containerOpacity }}>
      {containerAsset ? <img src={GUIDE_SETTINGS.assets.container} width="96" height="40" loading="lazy" decoding="async" alt="" onError={() => setContainerAsset(false)} /> : <svg viewBox="0 0 100 40"><rect x="1" y="1" width="98" height="37" rx="2" className="guide-container-shell" />{[10, 20, 30, 40, 50, 60, 70, 80, 90].map(x => <path key={x} d={`M${x} 4v30`} className="guide-container-rib" />)}<path d="M2 34h96" className="guide-container-rib" /></svg>}
    </motion.div>
  </div>;
}
