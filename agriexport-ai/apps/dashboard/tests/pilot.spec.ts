import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
const screenshots = resolve("../../data/screenshots");

test("public radar, filters, evidence drawer and four intelligence views", async ({ page }) => {
  const errors: string[] = []; page.on("pageerror", e => errors.push(e.message));
  await page.goto("/dashboard");
  await expect(page.getByText("Research mode. No live export recommendations.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Refresh data" })).toBeEnabled();
  await expect(page.getByText("API unavailable", { exact: true })).toHaveCount(0);
  const cards = page.getByRole("button", { name: "Review evidence & next steps" });
  if (await cards.count()) {
    await cards.first().click();
    await expect(page.getByRole("heading", { name: "Unresolved risks" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Verify before quoting" })).toBeVisible();
    await page.getByRole("button", { name: "Close evidence", exact: true }).click();
  }
  await page.getByRole("button", { name: "7 days", exact: true }).click();
  await page.getByLabel("Search product or market").fill("NO-SUCH-SYNTHETIC-PRODUCT");
  await expect(page.getByRole("heading", { name: "No matching signals" })).toBeVisible();
  await page.getByLabel("Search product or market").clear();
  await page.getByLabel("Show blocked", { exact: true }).uncheck();
  await expect(page.getByRole("heading", { name: "No matching signals" })).toBeVisible();
  await page.getByLabel("Show blocked", { exact: true }).check();
  mkdirSync(screenshots, { recursive: true });
  await page.screenshot({ path: resolve(screenshots, "phase4-radar-desktop.png"), fullPage: true });
  await page.getByRole("button", { name: "Country intelligence", exact: true }).click();
  await expect(page.getByLabel("Destination market", { exact: true })).toBeVisible();
  await expect(page.locator(".world-map path")).toHaveCount(177);
  const publicRows = await (await page.request.get("/api/backend/trade?limit=1000")).json();
  if (publicRows.some((row: { flow: string; reporter: string }) => row.flow === "M" && row.reporter === "156")) {
    await page.getByLabel("Destination market", { exact: true }).selectOption("156");
    await expect(page.getByRole("cell", { name: /Reporter China.*Imports/ })).toBeVisible();
  }
  await page.getByLabel("Destination market", { exact: true }).selectOption("840");
  await expect(page.getByRole("heading", { name: "No historical rows for this selection" })).toBeVisible();
  await page.getByRole("button", { name: "Commodity intelligence", exact: true }).click();
  await page.getByLabel("Commodity", { exact: true }).selectOption("tea");
  await expect(page.getByRole("heading", { name: "No historical rows for this selection" })).toBeVisible();
  await page.getByRole("button", { name: "Evidence & alerts", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Source & availability ledger" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Private evidence, protected by tenant" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("private credentials fail closed and leave no browser storage", async ({ page }) => {
  await page.goto("/dashboard"); await page.getByRole("button", { name: "Evidence & alerts", exact: true }).click();
  await page.getByRole("button", { name: "Connect your workspace", exact: true }).click();
  await page.getByLabel("API token", { exact: true }).fill("SYNTHETIC-INVALID-TOKEN");
  await page.getByRole("button", { name: "Connect securely" }).click();
  await expect(page.locator(".error[role=alert]")).toContainText("Invalid credentials");
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Private evidence, protected by tenant" })).toBeVisible();
});

test("backend outage surfaces error and does not substitute sample signals", async ({ page }) => {
  await page.route("**/api/backend/**", route => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "SYNTHETIC test outage" }) }));
  await page.goto("/dashboard"); await expect(page.locator(".error[role=alert]")).toContainText("SYNTHETIC test outage");
  await expect(page.getByRole("button", { name: "Review evidence & next steps" })).toHaveCount(0);
  await expect(page.getByText("API unavailable", { exact: true })).toBeVisible();
});

test("mobile navigation and viewport do not overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto("/dashboard");
  await expect(page.getByRole("button", { name: "Refresh data" })).toBeEnabled();
  await page.getByRole("button", { name: "Open navigation", exact: true }).click();
  await page.getByRole("button", { name: "Evidence & alerts", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Source & availability ledger" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBeTruthy();
  await page.screenshot({ path: resolve(screenshots, "phase4-evidence-mobile.png"), fullPage: true });
});

test("proxy rejects routes outside allowlist and anonymous writes", async ({ request }) => {
  expect((await request.get("/api/backend/commercial/audits")).status()).toBe(404);
  expect((await request.get("/api/backend/alerts")).status()).toBe(401);
  expect((await request.post("/api/backend/feedback", { data: {} })).status()).toBe(403);
  expect((await request.post("/api/backend/feedback", { headers: { Origin: "https://example.org", Authorization: "Bearer SYNTHETIC-BROWSER-A" }, data: {} })).status()).toBe(403);
});

test("SYNTHETIC private shipment feedback and preferences remain tenant isolated", async ({ page, request }) => {
  const categories = ["procurement", "processing", "packaging", "certification", "inland_transport", "origin_port", "export_clearance", "freight", "insurance", "destination_transport", "import_clearance", "duties", "taxes", "unloading", "financing", "other"];
  const buyer = new Set(["destination_transport", "import_clearance", "duties", "taxes", "unloading"]);
  const stamp = { quoted_at: new Date().toISOString(), published_at: new Date().toISOString(), expires_at: new Date(Date.now() + 60 * 86400000).toISOString() };
  const money = (amount: string, basis = "per_tonne") => ({ amount, basis, currency: "USD", evidence_reference: "SYNTHETIC browser fixture quote including documented zero", ...stamp });
  const headers = { Authorization: "Bearer SYNTHETIC-BROWSER-A" };
  const response = await request.post("http://127.0.0.1:8123/api/v1/commercial/quotes", { headers, data: {
    product_id: "basmati_rice", destination: "682", incoterm: "CIF", transport_mode: "sea", named_place: "SYNTHETIC port", shipment_tonnes: "20", buyer_quantity_tonnes: "20", verified_stock_tonnes: "20", logistics_capacity_tonnes: "20", capacity_evidence_reference: "SYNTHETIC browser capacity", buyer_reference: "SYNTHETIC buyer", logistics_reference: "SYNTHETIC carrier", reporting_currency: "USD", net_selling_price: money("1000"), contract_review_reference: "SYNTHETIC contract", synthetic: true, ...stamp,
    costs: categories.map(category => ({ category, payer: buyer.has(category) ? "buyer" : "seller", note: "SYNTHETIC allocation", money: buyer.has(category) ? null : money(category === "procurement" ? "500" : category === "freight" ? "1000" : "0", category === "freight" ? "per_shipment" : "per_tonne") }))
  } });
  expect(response.status()).toBe(201);
  const quote = await response.json();
  expect((await request.post("http://127.0.0.1:8123/api/v1/commercial/evaluate", { headers, data: { quote_id: quote.record_id, horizon_days: 7 } })).status()).toBe(201);
  await page.goto("/dashboard"); await page.getByRole("button", { name: "Evidence & alerts", exact: true }).click();
  await page.getByRole("button", { name: "Connect your workspace", exact: true }).click();
  await page.getByLabel("API token", { exact: true }).fill("SYNTHETIC-BROWSER-A");
  await page.getByRole("button", { name: "Connect securely" }).click();
  await expect(page.getByLabel("Decision", { exact: true })).toBeVisible();
  await page.getByLabel("Outcome", { exact: true }).selectOption("shipped");
  await page.getByLabel("Evidence reference", { exact: true }).fill("SYNTHETIC invoice reference");
  await page.getByLabel("Notes", { exact: true }).fill("SYNTHETIC browser shipment, not a commercial result");
  await page.getByLabel("Quantity (tonnes)", { exact: true }).fill("20");
  await page.getByLabel("Actual net revenue", { exact: true }).fill("20000");
  await page.getByLabel("Actual total seller cost", { exact: true }).fill("12000");
  await page.getByRole("button", { name: "Save self-reported outcome", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Outcome saved as self-reported");
  await expect(page.getByRole("cell", { name: "shipped", exact: true })).toBeVisible();
  const outcomes = await (await request.get("http://127.0.0.1:8123/api/v1/feedback", { headers })).json();
  expect(outcomes[0].realised_profit_per_shipment).toBe("8000");
  expect(outcomes[0].synthetic).toBe(true);
  await page.getByLabel("Margin threshold / tonne", { exact: true }).fill("500");
  await page.getByRole("button", { name: "Save preference", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Alert preference saved");
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await page.getByRole("button", { name: "Connect your workspace", exact: true }).click();
  await page.getByLabel("API token", { exact: true }).fill("SYNTHETIC-BROWSER-B");
  await page.getByRole("button", { name: "Connect securely" }).click();
  await expect(page.getByRole("heading", { name: "No stored commercial decisions", exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "shipped", exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => [localStorage.length, sessionStorage.length])).toEqual([0, 0]);
});
