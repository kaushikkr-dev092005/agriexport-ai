"use client";
import { useEffect, useRef, type RefObject } from "react";
import type { MotionValue } from "motion/react";
import { GUIDE_SETTINGS } from "./guideStops";

export type ExhaustSource = { x: number; y: number; angle: number; direction: number; visible: boolean };
type Particle = { x: number; y: number; vx: number; vy: number; age: number; life: number; radius: number; alpha: number };

/** One cached radial puff texture, bounded particles, event-woken rAF, visibility suspension. */
export function SmokeEmitter({ source, velocity, activity, width, height, mobile }: { source: RefObject<ExhaustSource>; velocity: MotionValue<number>; activity: RefObject<{ lastInput: number }>; width: number; height: number; mobile: boolean }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current, context = element?.getContext("2d", { alpha: true });
    if (!element || !context) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 1.25);
    element.width = Math.round(width * dpr); element.height = Math.round(height * dpr);
    context.setTransform(dpr, 0, 0, dpr, 0, 0);
    const buffer = document.createElement("canvas"); buffer.width = buffer.height = 64;
    const brush = buffer.getContext("2d"); if (!brush) return;
    const color = getComputedStyle(element).getPropertyValue("--land-muted").trim();
    const gradient = brush.createRadialGradient(32, 32, 0, 32, 32, 32); gradient.addColorStop(0, color); gradient.addColorStop(1, "transparent");
    brush.fillStyle = gradient; brush.fillRect(0, 0, 64, 64);
    let particles: Particle[] = [], frame = 0, last = 0, emission = 0;
    const cap = mobile ? GUIDE_SETTINGS.mobileParticles : GUIDE_SETTINGS.desktopParticles;
    const clear = () => { particles = []; context.clearRect(0, 0, width, height); element.dataset.particleCount = "0"; };
    const tick = (now: number) => {
      frame = 0;
      if (document.hidden || !source.current.visible) { clear(); return; }
      const dt = Math.min(.05, Math.max(.001, (now - last) / 1000)); last = now;
      const age = now - activity.current.lastInput, speed = Math.min(1, Math.abs(velocity.get()) / 1800);
      if (age < GUIDE_SETTINGS.idleSmokeMs) emission += dt * (mobile ? .8 + speed * 4 : 2 + speed * 12);
      while (emission >= 1 && particles.length < cap) {
        emission -= 1;
        const s = source.current, radians = s.angle * Math.PI / 180, direction = s.direction;
        particles.push({ x: s.x, y: s.y, vx: -Math.cos(radians) * direction * (17 + speed * 42) + (Math.random() - .5) * 6,
          vy: -Math.sin(radians) * direction * (17 + speed * 42) - 14, age: 0, life: 1.2 + Math.random() * .8,
          radius: (mobile ? 3 : 5) + speed * 8, alpha: mobile ? .065 : .12 });
      }
      emission = Math.min(emission, 1);
      context.clearRect(0, 0, width, height);
      particles = particles.filter(p => p.age < p.life);
      for (const p of particles) { p.age += dt; p.x += p.vx * dt; p.y += p.vy * dt; const radius = p.radius * (1 + p.age * .9); context.globalAlpha = Math.max(0, p.alpha * (1 - p.age / p.life)); context.drawImage(buffer, p.x - radius, p.y - radius, radius * 2, radius * 2); }
      context.globalAlpha = 1; element.dataset.particleCount = String(particles.length);
      if (particles.length || age < GUIDE_SETTINGS.idleSmokeMs) frame = requestAnimationFrame(tick);
    };
    const wake = () => { if (!frame && !document.hidden && source.current.visible) { last = performance.now(); frame = requestAnimationFrame(tick); } };
    const unsubscribe = velocity.on("change", wake);
    const visibility = () => { cancelAnimationFrame(frame); frame = 0; clear(); if (!document.hidden && performance.now() - activity.current.lastInput < GUIDE_SETTINGS.idleSmokeMs) wake(); };
    document.addEventListener("visibilitychange", visibility);
    return () => { unsubscribe(); document.removeEventListener("visibilitychange", visibility); cancelAnimationFrame(frame); clear(); };
  }, [source, velocity, activity, width, height, mobile]);
  return <canvas ref={canvas} className="guide-smoke" aria-hidden="true" data-particle-cap={mobile ? GUIDE_SETTINGS.mobileParticles : GUIDE_SETTINGS.desktopParticles} />;
}
