/** Edit copy/targets here. No deal pages are invented by this guide. */
export type GuideStopConfig = {
  id: string; label: string; section: string; target: string; copy: string;
  cta: string; href: string; fallback?: string; scene?: "export" | "import";
};

export const GUIDE_STOPS: GuideStopConfig[] = [
  { id: "hero", label: "Start here", section: ".land-hero", target: ".hero-actions .land-cta-shell", copy: "Start here. I'll show you around.", cta: "Explore the workspace", href: "/dashboard" },
  { id: "platform", label: "The platform", section: "#platform", target: "#platform .land-text-link", copy: "See demand, risks and prices in one view.", cta: "Open dashboard", href: "/dashboard" },
  { id: "approach", label: "Our approach", section: "#approach", target: "[data-guide-target='approach']", copy: "Every figure comes with its evidence.", cta: "See how it works", href: "#approach" },
  // TODO: Replace href/target when a genuine export-deals route is implemented.
  { id: "export", label: "Export deals", section: "#export-guide-stop", target: "[data-guide-target='export']", copy: "Looking to ship out? Browse export opportunities.", cta: "Browse export deals", href: "/dashboard", fallback: "Export deals route pending. Opens the opportunity dashboard.", scene: "export" },
  // TODO: Replace href/target when a genuine import-deals route is implemented.
  { id: "import", label: "Import deals", section: "#import-guide-stop", target: ".land-honesty a", copy: "Sourcing inputs? Check import trade deals.", cta: "Browse import deals", href: "/dashboard#evidence", fallback: "Import deals route pending. Opens source evidence, not a deal listing.", scene: "import" },
  { id: "questions", label: "Questions", section: "#questions", target: "#questions details:first-of-type summary", copy: "Still unsure? Start with the basics.", cta: "Read the FAQ", href: "#questions" },
];

export const GUIDE_SETTINGS = {
  storageKey: "agriexport-truck-guide-hidden", stopRadius: .035, stopHoldRadius: .004,
  smoothingMs: 145, idleSmokeMs: 2200, desktopParticles: 60, mobileParticles: 12,
  // Asset coordinates are relative to the 160 x 82 sprite, before tangent rotation.
  exhaustOffset: { x: 121, y: 20 }, truckWidth: 104, tabletTruckWidth: 82,
  assets: { truck: "/guide/truck.webp", container: "/guide/container.webp", crane: "/guide/crane.webp" },
} as const;
