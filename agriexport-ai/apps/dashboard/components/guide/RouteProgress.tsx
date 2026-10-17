"use client";
import { useTransform, motion, type MotionValue } from "motion/react";

/** Page progress only, not a real shipment percentage. */
export function RouteProgress({ progress }: { progress: MotionValue<number> }) {
  return <div className="guide-route-progress" aria-hidden="true"><span>PAGE ROUTE</span><div>{Array.from({ length: 6 }, (_, i) => <ProgressSegment key={i} progress={progress} index={i} />)}</div></div>;
}
function ProgressSegment({ progress, index }: { progress: MotionValue<number>; index: number }) {
  const opacity = useTransform(progress, p => p >= index / 6 ? 1 : .18);
  return <motion.i style={{ opacity }} />;
}
