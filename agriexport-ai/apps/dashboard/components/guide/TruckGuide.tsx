"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useMotionValue } from "motion/react";
import { Route, X } from "lucide-react";
import { GUIDE_SETTINGS, GUIDE_STOPS } from "./guideStops";
import { createRoad, overlaps, routePhase, clamp, type Box } from "./geometry";
import { useScrollProgress } from "./useScrollProgress";
import { useGuideSections } from "./useGuideSections";
import { RoadPath } from "./RoadPath";
import { TruckSprite } from "./TruckSprite";
import { SmokeEmitter, type ExhaustSource } from "./SmokeEmitter";
import { GuideStop } from "./GuideStop";
import { TargetHighlight } from "./TargetHighlight";
import { GlassStatCard } from "./GlassStatCard";
import { ContainerLoadScene } from "./ContainerLoadScene";
import { RouteProgress } from "./RouteProgress";
import "./guide.css";

/** Landing-only progressive enhancement; normal-page links remain usable without this layer. */
export default function TruckGuide({ paused = false }: { paused?: boolean }) {
  const [reducedMotion, setReducedMotion] = useState(false);
  const [ready, setReady] = useState(false), [hidden, setHidden] = useState(false);
  useEffect(() => { try { setHidden(localStorage.getItem(GUIDE_SETTINGS.storageKey) === "true"); } catch { /* Storage is optional. */ } setReady(true); }, []);
  useEffect(() => {
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(media.matches);
    update(); media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  if (!ready || paused) return null;
  const toggle = () => { const next = !hidden; setHidden(next); try { localStorage.setItem(GUIDE_SETTINGS.storageKey, String(next)); } catch { /* Private browsing/storage denial must not break navigation. */ } };
  return <div className="truck-guide" data-truck-guide="true" data-hidden={hidden} data-reduced-motion={!!reducedMotion}>
    <button className="guide-toggle" onClick={toggle} aria-expanded={!hidden} aria-label={hidden ? "Show truck guide" : "Hide truck guide"}><Route size={13} />{hidden ? "Show guide" : "Hide guide"}</button>
    {!hidden && (reducedMotion ? <StaticGuide /> : <MovingGuide />)}
  </div>;
}

function StaticGuide() {
  const wheel = useMotionValue(0), bob = useMotionValue(0);
  return <div className="guide-static"><div className="guide-static-truck"><TruckSprite wheelAngle={wheel} bob={bob} compact /></div><a href="#guide-shortcuts" aria-label="Next stops: read the static page guide">Next stops <Route size={12} /></a></div>;
}

function MovingGuide() {
  const { anchors, protectedBoxes, size, inView } = useGuideSections();
  const { progress, velocity, rawProgress, scrollY, activity } = useScrollProgress(anchors);
  const road = useMemo(() => createRoad(size.width, size.height), [size.width, size.height]);
  const mobile = size.width < 768, truckWidth = mobile ? 36 : size.width < 1024 ? GUIDE_SETTINGS.tabletTruckWidth : GUIDE_SETTINGS.truckWidth;
  const [active, setActive] = useState<number | null>(0), [sheet, setSheet] = useState(false);
  const activeRef = useRef<number | null>(0), inViewRef = useRef(inView); inViewRef.current = inView;
  const truck = useRef<HTMLDivElement>(null), tooltip = useRef<HTMLDivElement>(null), ambient = useRef<HTMLDivElement>(null), layer = useRef<HTMLDivElement>(null);
  const tooltipSize = useRef({ width: 166, height: 230 });
  const exhaust = useRef<ExhaustSource>({ x: 0, y: 0, angle: 0, direction: 1, visible: false });
  useEffect(() => {
    if (!sheet) return;
    const control = layer.current?.querySelector<HTMLButtonElement>(".guide-open-sheet");
    layer.current?.querySelector<HTMLButtonElement>(".guide-sheet-close")?.focus({ preventScroll: true });
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") setSheet(false); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); control?.focus({ preventScroll: true }); };
  }, [sheet]);
  const wheel = useMotionValue(0), bob = useMotionValue(0);
  useEffect(() => {
    const node = tooltip.current; if (!node) return;
    const observer = new ResizeObserver(entries => { const entry = entries[0]; if (entry) tooltipSize.current = { width: entry.contentRect.width, height: entry.contentRect.height }; });
    observer.observe(node); return () => observer.disconnect();
  }, [active]);
  useEffect(() => {
    let lastPhase = routePhase(progress.get(), anchors.current), pending = 0;
    const update = () => {
      pending = 0;
      const p = progress.get(), phase = routePhase(p, anchors.current), raw = rawProgress.get(), currentY = scrollY.get();
      const position = mobile ? { x: size.width - 16, y: size.height * .52, angle: -90 } : road.sample(phase);
      const direction = activity.current.direction;
      const boxes = protectedBoxes.current.map(b => ({ ...b, y: b.y - currentY }));
      const safe = (box: Box) => !boxes.some(b => overlaps(box, b));
      const footprint = { x: position.x - truckWidth * .36, y: position.y - truckWidth * .36, width: truckWidth * .72, height: truckWidth * .72 };
      const visible = mobile || safe(footprint);
      if (truck.current) {
        truck.current.style.transform = `translate3d(${position.x}px,${position.y}px,0) translate(-50%,-50%) rotate(${position.angle}deg) scaleX(${direction})`;
        truck.current.style.opacity = visible ? "1" : "0";
      }
      wheel.set(wheel.get() + (phase - lastPhase) * 12500); lastPhase = phase;
      bob.set(Math.sin(wheel.get() * .02) * Math.min(1.3, Math.abs(velocity.get()) / 1700));
      const offset = GUIDE_SETTINGS.exhaustOffset, radians = position.angle * Math.PI / 180, scale = truckWidth / 160;
      const ox = (offset.x - 80) * scale * direction, oy = (offset.y - 41) * scale;
      exhaust.current = { x: position.x + ox * Math.cos(radians) - oy * Math.sin(radians), y: position.y + ox * Math.sin(radians) + oy * Math.cos(radians), angle: position.angle, direction, visible };
      const index = anchors.current.findIndex((a, i) => Math.abs(raw - a) <= GUIDE_SETTINGS.stopRadius && inViewRef.current.has(i));
      const selected = index < 0 ? null : index;
      if (activeRef.current !== selected) { activeRef.current = selected; setActive(selected); }
      if (layer.current) { layer.current.dataset.routePhase = phase.toFixed(4); layer.current.dataset.scrollDirection = direction > 0 ? "down" : "up"; layer.current.dataset.activeStop = selected === null ? "" : GUIDE_STOPS[selected].id; layer.current.dataset.scene = Math.abs(raw - anchors.current[3]) < .07 ? "export" : Math.abs(raw - anchors.current[4]) < .07 ? "import" : ""; }
      if (tooltip.current && !mobile && selected !== null) {
        const { width, height } = tooltipSize.current;
        const xs = [position.x < size.width / 2 ? 10 : size.width - width - 10, position.x < size.width / 2 ? size.width - width - 10 : 10];
        const ys = [clamp(position.y + 58, 112, size.height - height - 46), clamp(position.y - height - 48, 112, size.height - height - 46), 115, size.height - height - 45];
        const scanY = Array.from({ length: Math.max(0, Math.floor((size.height - height - 158) / 24)) }, (_, i) => 112 + i * 24);
        const truckClearance = { x: position.x - truckWidth / 2, y: position.y - truckWidth / 2, width: truckWidth, height: truckWidth + 20 };
        const place = xs.flatMap(x => [...ys, ...scanY].map(y => ({ x, y, width, height }))).find(box => safe(box) && !overlaps(box, truckClearance));
        tooltip.current.style.opacity = place ? "1" : "0";
        tooltip.current.style.visibility = place ? "visible" : "hidden";
        if (place) { tooltip.current.style.transform = `translate3d(${place.x}px,${place.y}px,0)`; tooltip.current.dataset.x = String(place.x); tooltip.current.dataset.y = String(place.y); }
      }
      if (ambient.current) {
        const width = 164, height = 158;
        const candidates = [size.height - height - 90, 150, size.height * .5 - height / 2].flatMap(y => [24, size.width - width - 24].map(x => ({ x, y, width, height })));
        const place = !mobile && (selected === 1 || selected === 3) ? candidates.find(b => safe(b) && (!tooltip.current || !overlaps(b, { x: Number(tooltip.current.dataset.x || -500), y: Number(tooltip.current.dataset.y || -500), ...tooltipSize.current }))) : undefined;
        ambient.current.style.opacity = place ? ".94" : "0";
        if (place) ambient.current.style.transform = `translate3d(${place.x}px,${place.y}px,0)`;
      }
    };
    const schedule = () => { if (!pending) pending = requestAnimationFrame(update); };
    const cancelProgress = progress.on("change", schedule), cancelVelocity = velocity.on("change", schedule), cancelRaw = rawProgress.on("change", schedule);
    update();
    return () => { cancelProgress(); cancelVelocity(); cancelRaw(); cancelAnimationFrame(pending); };
  }, [anchors, protectedBoxes, progress, rawProgress, scrollY, velocity, road, size, mobile, truckWidth, activity, wheel, bob, inView, active]);
  const stop = GUIDE_STOPS[active ?? Math.max(0, anchors.current.findLastIndex(a => rawProgress.get() >= a))];
  return <div className="guide-motion-layer" ref={layer} data-mode={mobile ? "mobile" : size.width < 1024 ? "tablet" : "desktop"}>
    {!mobile && <RoadPath d={road.d} width={size.width} height={size.height} protectedBoxes={protectedBoxes.current} scrollY={scrollY} />}
    <SmokeEmitter source={exhaust} velocity={velocity} activity={activity} width={size.width} height={size.height} mobile={mobile} />
    <div ref={truck} className="guide-truck-anchor" style={{ width: truckWidth }} aria-hidden="true"><TruckSprite wheelAngle={wheel} bob={bob} compact={mobile}><ContainerLoadScene progress={rawProgress} anchors={anchors} scale={truckWidth / 160} /></TruckSprite></div>
    <TargetHighlight selector={active === null ? undefined : stop.target} />
    {!mobile && active !== null && <div className="guide-tooltip-anchor" ref={tooltip}><GuideStop stop={stop} /></div>}
    <div className="guide-ambient-anchor" ref={ambient}>{active === 1 ? <GlassStatCard variant="growth" /> : active === 3 ? <GlassStatCard variant="shipments" /> : null}</div>
    <button className="guide-open-sheet" aria-label={`Open truck guide: ${stop.label}`} onClick={() => setSheet(true)}><Route size={14} /><span>{mobile ? "Guide" : "Stop details"}</span></button>
    {sheet && <div className="guide-sheet" role="region" aria-label="Truck guide stop details"><button className="guide-sheet-close" aria-label="Close guide details" onClick={() => setSheet(false)}><X size={16} /></button><GuideStop stop={stop} mobile onClose={() => setSheet(false)} /></div>}
    <RouteProgress progress={rawProgress} />
  </div>;
}

/** Ordinary document navigation: remains available with hidden guide, reduced motion or no JS. */
export function GuideShortcuts() {
  return <nav className="guide-shortcuts" id="guide-shortcuts" aria-label="Page guide shortcuts"><span>YOUR NEXT STOPS</span><div>{GUIDE_STOPS.map(s => <a key={s.id} href={s.href} aria-label={`Guide shortcut: ${s.cta}`} title={s.fallback}>{s.id === "platform" ? "Dashboard" : s.label}{s.fallback && <small>Overview · route pending</small>}</a>)}</div><small>Asset TODO: replace truck, container and crane placeholders with final licensed cutouts.</small></nav>;
}
