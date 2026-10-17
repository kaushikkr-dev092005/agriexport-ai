import { useId } from "react";
import { motion, useTransform, type MotionValue } from "motion/react";
import type { Box } from "./geometry";
/** Perimeter clipping keeps decorative road paint out of the page's reading column. */
export function RoadPath({ d, width, height, protectedBoxes, scrollY }: { d: string; width: number; height: number; protectedBoxes: Box[]; scrollY: MotionValue<number> }) {
  const id = useId();
  const y = useTransform(scrollY, value => -value);
  return <svg className="guide-road" viewBox={`0 0 ${width} ${height}`} aria-hidden="true"><defs><clipPath id={id}><rect x="0" y="110" width="76" height={height - 110} /><rect x={width - 76} y="110" width="76" height={height - 110} /><rect x="0" y={height - 65} width={width} height="36" /></clipPath><mask id={`${id}-clear`} maskUnits="userSpaceOnUse"><rect width={width} height={height} fill="white" /><motion.g style={{ y }}>{protectedBoxes.map((b, i) => <rect key={i} x={b.x - 9} y={b.y - 9} width={b.width + 18} height={b.height + 18} fill="black" />)}</motion.g></mask></defs><g clipPath={`url(#${id})`} mask={`url(#${id}-clear)`}><path d={d} className="guide-road-bed" /><path d={d} className="guide-road-dashes" /></g></svg>;
}
