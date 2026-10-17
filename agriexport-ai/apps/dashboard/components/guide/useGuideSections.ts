"use client";
import { useEffect, useRef, useState } from "react";
import { GUIDE_STOPS } from "./guideStops";
import { clamp, type Box } from "./geometry";

/** Geometry reads happen on resize/content change, not in scroll frames. IO detects sections. */
export function useGuideSections() {
  const anchors = useRef(GUIDE_STOPS.map((_, i) => i / (GUIDE_STOPS.length - 1)));
  const protectedBoxes = useRef<Box[]>([]);
  const [size, setSize] = useState({ width: 1440, height: 900 });
  const [inView, setInView] = useState<Set<number>>(new Set([0]));
  useEffect(() => {
    let pending = 0;
    const measure = () => {
      pending = 0;
      const y = window.scrollY, height = window.innerHeight, range = Math.max(1, document.documentElement.scrollHeight - height);
      setSize({ width: window.innerWidth, height });
      anchors.current = GUIDE_STOPS.map((s, i) => {
        const node = document.querySelector(s.section);
        return i === 0 ? 0 : clamp(((node?.getBoundingClientRect().top ?? 0) + y - height * .33) / range);
      });
      const boxes: Box[] = [];
      for (const node of document.querySelectorAll<HTMLElement>(".landing h1,.landing h2,.landing h3,.landing p,.landing blockquote,.landing a,.landing summary,.landing button,.landing .concept-card,.landing .land-section-label")) {
        if (node.closest("[data-truck-guide]") || !node.getClientRects().length) continue;
        // Block paragraphs can span the entire viewport despite centered short text.
        // Cache actual text runs; keep whole hit areas for links, buttons and UI cards.
        if (node.matches("a,button,summary,.concept-card")) {
          const r = node.getBoundingClientRect(); boxes.push({ x: r.x, y: r.y + y, width: r.width, height: r.height });
        } else {
          const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
          while (walker.nextNode()) {
            if (!walker.currentNode.textContent?.trim()) continue;
            const range = document.createRange(); range.selectNodeContents(walker.currentNode);
            for (const r of range.getClientRects()) if (r.width && r.height) boxes.push({ x: r.x, y: r.y + y, width: r.width, height: r.height });
          }
        }
      }
      protectedBoxes.current = boxes;
    };
    const schedule = () => { if (!pending) pending = requestAnimationFrame(measure); };
    const observer = new IntersectionObserver(entries => {
      setInView(previous => {
        const next = new Set(previous);
        for (const entry of entries) { const index = GUIDE_STOPS.findIndex(s => document.querySelector(s.section) === entry.target); if (index >= 0) { if (entry.isIntersecting) next.add(index); else next.delete(index); } }
        return next;
      });
    }, { rootMargin: "-18% 0px -34% 0px", threshold: 0 });
    GUIDE_STOPS.forEach(s => { const node = document.querySelector(s.section); if (node) observer.observe(node); });
    const resize = new ResizeObserver(schedule); resize.observe(document.querySelector(".landing") || document.body);
    window.addEventListener("resize", schedule, { passive: true });
    document.fonts.ready.then(schedule);
    measure();
    return () => { observer.disconnect(); resize.disconnect(); window.removeEventListener("resize", schedule); cancelAnimationFrame(pending); };
  }, []);
  return { anchors, protectedBoxes, size, inView };
}
