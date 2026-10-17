"use client";
import { useEffect, useRef, type RefObject } from "react";
import { useMotionValue, useScroll } from "motion/react";
import { GUIDE_SETTINGS } from "./guideStops";
import { clamp } from "./geometry";

/** Motion supplies scroll events; one rAF sampler eases MotionValues, never React state. */
export function useScrollProgress(anchors: RefObject<number[]>) {
  const { scrollYProgress, scrollY } = useScroll();
  const progress = useMotionValue(0), velocity = useMotionValue(0);
  const activity = useRef({ lastInput: -1e9, direction: 1, inputY: 0 });
  useEffect(() => {
    let frame = 0, previousTime = performance.now(), inputTime = previousTime, previousY = scrollY.get(), targetVelocity = 0;
    const tick = (now: number) => {
      frame = 0;
      if (document.hidden) return;
      const dt = Math.min(50, Math.max(1, now - previousTime)); previousTime = now;
      const raw = clamp(scrollYProgress.get());
      let target = raw;
      for (const anchor of anchors.current) {
        const distance = raw - anchor;
        if (Math.abs(distance) < GUIDE_SETTINGS.stopRadius) {
          target = Math.abs(distance) < GUIDE_SETTINGS.stopHoldRadius ? anchor : anchor + distance * Math.abs(distance) / GUIDE_SETTINGS.stopRadius;
          break;
        }
      }
      const next = progress.get() + (target - progress.get()) * (1 - Math.exp(-dt / GUIDE_SETTINGS.smoothingMs));
      progress.set(Math.abs(target - next) < .00001 ? target : next);
      const desiredSpeed = now - activity.current.lastInput > 85 ? 0 : targetVelocity;
      velocity.set(velocity.get() + (desiredSpeed - velocity.get()) * (1 - Math.exp(-dt / 90)));
      if (Math.abs(velocity.get()) < .5 && desiredSpeed === 0) velocity.set(0);
      if (Math.abs(progress.get() - target) > .00001 || Math.abs(velocity.get()) > .5 || now - activity.current.lastInput < 160) frame = requestAnimationFrame(tick);
    };
    const wake = () => { if (!frame && !document.hidden) { previousTime = performance.now(); frame = requestAnimationFrame(tick); } };
    const unsubscribe = scrollY.on("change", y => {
      const now = performance.now(), delta = y - previousY;
      targetVelocity = clamp(delta / Math.max(8, now - inputTime) * 1000, -3200, 3200);
      if (Math.abs(delta) > .1) { activity.current.lastInput = now; activity.current.direction = delta > 0 ? 1 : -1; }
      activity.current.inputY = y; previousY = y; inputTime = now; wake();
    });
    const stop = () => { if (document.hidden) { cancelAnimationFrame(frame); frame = 0; velocity.set(0); } else wake(); };
    document.addEventListener("visibilitychange", stop);
    progress.set(scrollYProgress.get()); activity.current.inputY = scrollY.get(); wake();
    return () => { unsubscribe(); cancelAnimationFrame(frame); document.removeEventListener("visibilitychange", stop); };
  }, [anchors, progress, velocity, scrollY, scrollYProgress]);
  return { progress, velocity, rawProgress: scrollYProgress, scrollY, activity };
}
