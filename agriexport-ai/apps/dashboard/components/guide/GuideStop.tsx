import { ArrowUpRight, Route } from "lucide-react";
import type { GuideStopConfig } from "./guideStops";

/** The text is visual decoration; each CTA carries the complete screen-reader context. */
export function GuideStop({ stop, mobile = false, onClose }: { stop: GuideStopConfig; mobile?: boolean; onClose?: () => void }) {
  return <aside className={`guide-stop ${mobile ? "guide-stop-sheet" : ""}`} data-stop-id={stop.id}>
    <div aria-hidden="true"><span className="guide-stop-kicker"><Route size={12} />YOUR ROUTE GUIDE</span><strong>{stop.label}</strong><p>{stop.copy}</p></div>
    <a href={stop.href} aria-label={`Guide: ${stop.cta}${stop.fallback ? ". " + stop.fallback : ""}`} onClick={onClose}><span>{stop.cta}</span><ArrowUpRight size={13} /></a>
    {stop.fallback && <small aria-hidden="true">{stop.fallback}</small>}
    {mobile && <small aria-hidden="true">TODO: replace truck, container and crane with final assets.</small>}
  </aside>;
}
