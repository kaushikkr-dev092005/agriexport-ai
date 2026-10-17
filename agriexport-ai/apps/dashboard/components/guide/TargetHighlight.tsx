"use client";
import { useEffect } from "react";

/** Outline an actual page element; no cloned controls, geometry polling or click interception. */
export function TargetHighlight({ selector }: { selector?: string }) {
  useEffect(() => {
    if (!selector) return;
    const target = document.querySelector<HTMLElement>(selector);
    if (!target) return;
    target.classList.add("guide-highlight-target");
    return () => target.classList.remove("guide-highlight-target");
  }, [selector]);
  return null;
}
