import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { GUIDE_STOPS } from "../components/guide/guideStops";
import { createRoad, routePhase, sceneLift } from "../components/guide/geometry";

async function stopAt(page: Page, index: number) {
  await page.evaluate(({ section, index }) => {
    window.scrollTo({ top: index === 0 ? 0 : document.querySelector(section)!.getBoundingClientRect().top + scrollY - innerHeight * .33, behavior: "instant" });
  }, { section: GUIDE_STOPS[index].section, index });
  await expect(page.locator(".guide-motion-layer")).toHaveAttribute("data-active-stop", GUIDE_STOPS[index].id);
  await page.waitForTimeout(380);
}

test("route geometry and reversible container scrubbing stay deterministic", () => {
  for (const width of [768, 1440]) {
    const road = createRoad(width, 1000);
    for (let i = 0; i <= 100; i++) {
      const p = road.sample(i / 100);
      expect(Number.isFinite(p.angle)).toBeTruthy();
      expect(p.x).toBeGreaterThan(0); expect(p.x).toBeLessThan(width);
      expect(p.y).toBeGreaterThan(0); expect(p.y).toBeLessThan(1000);
    }
  }
  expect(routePhase(.5, [0, .2, .4, .6, .8, 1])).toBeCloseTo(.5);
  expect(sceneLift(.4, .5, "export")).toBe(1);
  expect(sceneLift(.6, .5, "export")).toBe(0);
  expect(sceneLift(.4, .5, "import")).toBe(0);
  expect(sceneLift(.6, .5, "import")).toBe(1);
  expect(sceneLift(.5, .5, "export")).toBeCloseTo(.5);
});

test("six desktop stops highlight real targets, link honestly, and reverse", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  page.on("console", m => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto("/");
  await expect(page.getByRole("button", { name: "Hide truck guide" })).toBeVisible();
  for (let i = 0; i < GUIDE_STOPS.length; i++) {
    await stopAt(page, i);
    await expect(page.locator(GUIDE_STOPS[i].target)).toHaveClass(/guide-highlight-target/);
    await expect(page.locator(".guide-tooltip-anchor")).toBeVisible();
    const truckBox = await page.locator(".guide-truck-anchor").boundingBox();
    const cardBox = await page.locator(".guide-tooltip-anchor").boundingBox();
    expect(truckBox && cardBox && truckBox.x < cardBox.x + cardBox.width && truckBox.x + truckBox.width > cardBox.x && truckBox.y < cardBox.y + cardBox.height && truckBox.y + truckBox.height > cardBox.y).toBeFalsy();
    await expect(page.locator(".guide-tooltip-anchor a")).toHaveAttribute("href", GUIDE_STOPS[i].href);
    if (GUIDE_STOPS[i].fallback) await expect(page.locator(".guide-tooltip-anchor")).toContainText(/route pending/);
    if (i === 1 || i === 3) await expect(page.locator(".guide-glass-stat")).toContainText("Sample data");
  }
  await stopAt(page, 3);
  await expect(page.locator(".guide-motion-layer")).toHaveAttribute("data-scroll-direction", "up");
  await expect(page.locator(".guide-motion-layer")).toHaveAttribute("data-scene", "export");
  const before = await page.locator(".guide-container").getAttribute("style");
  await page.evaluate(() => window.scrollBy({ top: 100, behavior: "instant" }));
  await page.waitForTimeout(400);
  expect(await page.locator(".guide-container").getAttribute("style")).not.toBe(before);
  await expect(page.locator(".guide-smoke")).toHaveAttribute("data-particle-cap", "60");
  await page.waitForTimeout(4600);
  await expect(page.locator(".guide-smoke")).toHaveAttribute("data-particle-count", "0");
  expect(errors).toEqual([]);
});

for (const width of [375, 768, 1440]) test(`guide at ${width}px preserves page controls and has no overflow`, async ({ page }) => {
  await page.setViewportSize({ width, height: 1000 });
  await page.goto("/");
  await expect(page.locator(".guide-motion-layer")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  await page.getByRole("link", { name: "Explore the workspace", exact: true }).click({ trial: true });
  for (let i = 0; i < GUIDE_STOPS.length; i++) await stopAt(page, i);
  await page.getByRole("button", { name: /Open truck guide:/ }).click();
  await expect(page.getByRole("region", { name: "Truck guide stop details" })).toBeVisible();
  await page.getByRole("button", { name: "Close guide details" }).click();
  await expect(page.locator(".guide-sheet")).toHaveCount(0);
  if (width === 375) await expect(page.locator(".guide-smoke")).toHaveAttribute("data-particle-cap", "12");
  await page.screenshot({ path: `../../data/screenshots/guide-tested-${width}.png` });
});

test("hide choice persists, keyboard toggle works and reduced motion is static", async ({ page }) => {
  await page.goto("/");
  const toggle = page.getByRole("button", { name: "Hide truck guide" });
  await toggle.focus(); await page.keyboard.press("Enter");
  await expect(page.locator(".guide-motion-layer")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("button", { name: "Show truck guide" })).toBeVisible();
  await page.getByRole("button", { name: "Show truck guide" }).click();
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(page.locator(".guide-static")).toBeVisible();
  await expect(page.locator(".guide-smoke,.guide-road")).toHaveCount(0);
  await expect(page.locator(".guide-shortcuts a")).toHaveCount(6);
  await page.getByRole("link", { name: "Guide shortcut: Open dashboard", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.locator("[data-truck-guide]")).toHaveCount(0);
});

test("denied storage does not break the optional guide", async ({ page }) => {
  await page.addInitScript(() => Object.defineProperty(window, "localStorage", { get() { throw new Error("Storage denied"); } }));
  await page.goto("/");
  await page.getByRole("button", { name: "Hide truck guide" }).click();
  await expect(page.getByRole("button", { name: "Show truck guide" })).toBeVisible();
});

test("moving smoke is bounded, hidden-tab suspension clears it, and frames are measured", async ({ page }, testInfo) => {
  await page.goto("/");
  await expect(page.locator(".guide-smoke")).toBeVisible();
  const result = await page.evaluate(async () => {
    const intervals: number[] = []; let previous = performance.now(), maxParticles = 0;
    for (let i = 0; i < 90; i++) {
      await new Promise<void>(resolve => requestAnimationFrame(now => { intervals.push(now - previous); previous = now; window.scrollTo(0, i * 6); resolve(); }));
      maxParticles = Math.max(maxParticles, Number(document.querySelector<HTMLCanvasElement>(".guide-smoke")?.dataset.particleCount || 0));
    }
    intervals.sort((a, b) => a - b);
    return { frames: intervals.length, medianMs: intervals[45], p95Ms: intervals[85], maxParticles };
  });
  expect(result.maxParticles).toBeGreaterThan(0);
  expect(result.maxParticles).toBeLessThanOrEqual(60);
  mkdirSync(resolve("../../data/screenshots"), { recursive: true });
  writeFileSync(resolve("../../data/screenshots/guide-frame-sample.json"), JSON.stringify({ ...result, note: "Headless Edge on this workstation; not a mid-range laptop certification." }, null, 2));
  await testInfo.attach("workstation-frame-sample.json", { body: JSON.stringify(result), contentType: "application/json" });
  await page.evaluate(() => { Object.defineProperty(document, "hidden", { configurable: true, value: true }); document.dispatchEvent(new Event("visibilitychange")); });
  await expect(page.locator(".guide-smoke")).toHaveAttribute("data-particle-count", "0");
});
