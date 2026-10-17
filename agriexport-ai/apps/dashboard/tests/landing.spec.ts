import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

test("editorial landing page, Aceternity components and workspace navigation", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Your next market. In clearer view." })).toBeVisible();
  await expect(page.locator(".landscape-art > img")).toBeVisible();
  expect(await page.locator(".landscape-art > img").evaluate((img: HTMLImageElement) => img.complete && img.naturalWidth > 100)).toBeTruthy();
  await page.getByRole("button", { name: "28 days", exact: true }).click();
  await expect(page.getByRole("link", { name: "Explore the 28-day workspace" })).toBeVisible();
  await expect(page.getByText("ILLUSTRATIVE, NOT A LIVE SIGNAL", { exact: true })).toBeVisible();
  await page.getByText("Is this a live export recommendation service?", { exact: true }).click();
  await expect(page.getByText(/Not yet. AgriExport AI is a working research pilot/)).toBeVisible();
  await page.emulateMedia({ reducedMotion: "reduce" });
  mkdirSync(resolve("../../data/screenshots"), { recursive: true });
  await page.screenshot({ path: resolve("../../data/screenshots/landing-desktop.png"), fullPage: true });
  await page.getByRole("link", { name: "Explore the workspace", exact: true }).click();
  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByText("Research mode. No live export recommendations.")).toBeVisible();
  expect(errors).toEqual([]);
});

test("mobile landing, menu, FAQ and reduced motion", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("button", { name: "Open menu", exact: true }).click();
  await page.getByRole("navigation", { name: "Mobile navigation" }).getByRole("link", { name: "Questions", exact: true }).click();
  await expect(page.getByText("Is this a live export recommendation service?", { exact: true })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: resolve("../../data/screenshots/landing-mobile.png"), fullPage: true });
});
