import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "AgriExport AI | Your next market, in clearer view", description: "An evidence-led agricultural export intelligence workspace for Indian exporters. Explore markets, review sources and verify commercial opportunities before quoting." };
export default function Layout({ children }: { children: React.ReactNode }) { return <html lang="en"><body>{children}</body></html>; }
