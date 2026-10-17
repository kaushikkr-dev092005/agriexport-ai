# Phase 4 status — 2026-10-16

**Local software pilot implemented.** Landing page, dashboard, feedback, internal
alerts and workflow definitions work. This is not a completed prospective exporter
trial, a validated forecasting model or an unattended production deployment.

## Working and measured

- Next.js 16.4.2 / React / TypeScript production build and type checking pass.
  The landing at `/` follows the requested warm editorial Figr direction, using
  Aceternity UI's actual Bento Grid, Hover Border Gradient and Text Generate Effect.
  Original generated landscape artwork is decorative and explicitly identified.
- `/dashboard` has all four views: opportunity radar, country intelligence,
  commodity history, and evidence with private decisions, alerts and feedback.
  Search, categories, 7/14/28-day filters, blocked visibility, source drawers,
  market/product selectors, source dates and the reference map work.
- **8 Playwright browser tests passed** in Microsoft Edge: desktop/mobile landing,
  FAQ and navigation, dashboard views/filters/drawer, API outage, invalid credentials,
  no credential browser storage, proxy restrictions, SYNTHETIC shipment feedback,
  preference saves and tenant switching. Screenshots were visually inspected.
- **101 Python tests passed with isolated PostgreSQL enabled**, including schema
  comparison, restricted-role RLS, private quote/outcome operations, cross-tenant
  checks, accounting, point-in-time guards, material alerts, workflow readiness and
  schedule definitions. SQLite-only with automation: 99 passed, 2 PostgreSQL skips.
- Ruff lint/format checks pass. Upstream Starlette/httpx and MLflow/SQLAlchemy
  deprecation warnings remain. Browser tooling also emits a harmless color-env warning.
- The one-command preview launcher actually served landing, dashboard and API,
  passed HTTP checks, and stopped its owned servers. No OS service was installed.
- Real PostgreSQL HTTP smoke: 19 products, 2 genuine monthly trade observations,
  6 stored seasonal contexts, 6 blocked candidates; details/docs and auth rejection pass.
- A real Prefect one-shot daily flow ran: 6 stored contexts; DEGRADED because source
  jobs were not configured; 0 tenant runs and 0 outbound messages.
- A real Prefect/MLflow weekly readiness run completed as SKIPPED_DATA_NOT_READY
  (run `8f8a48ed362c4e778f39a621e48855f3`). An explicit SYNTHETIC baseline-evaluation
  run also completed (run `906317b3cfa641e19052d5763e287c8d`). Neither trained or
  promoted a learned model. Their IDs refer to this checkout's local tracking store.

## Data and commercial boundaries

Genuine source samples are January 2025 India-to-Saudi-Arabia basmati exports and
January 2024 China-from-World rice imports. These old monthly records are not current
weekly demand, stock, freight or selling-price quotations. Earlier NASA POWER and
APHIS retrieval checks are described in PHASE2/PHASE3. APEDA/UN legal-text probe
limitations remain unresolved. No current legal clearance was inferred.

Broad catalogue coverage is 19 starter product entries, not every food SKU or exact
ITC edition. Most headings cannot pass exact legal mapping. Demand/price baselines,
chronological backtests, source availability/revisions and unknown-value behaviour
remain separate from commercial accounting and decisions.

Conditional quote accounting, human policy/risk reviews and tenant-private APIs
work. New quotation cost revisions preserve lineage and reset approvals. Current
real contexts have missing DGFT/import/SPS/sanctions evidence, current quotes,
verified supply, validated demand and calibrated confidence, so their ranking stays
BLOCKED_OR_UNVERIFIED. No real profitable shipment or export success is claimed.

Feedback is append-only SELF_REPORTED_UNVERIFIED, with prospective event-time and
idempotency checks. Shipment accounting requires explicit quantity/currency/revenue/
cost. It does not turn a reported sale into verified model success. All browser test
quotes/outcomes and their account identities are clearly SYNTHETIC.

## Automation and deployment boundaries

- Daily jobs are explicit opt-in Commerce/Comtrade queries in configs/pipeline.yaml.
  Empty configuration and source outages are surfaced. Latest real private quotation
  versions are re-evaluated per tenant and horizon before material-change alerts.
- Alerts require preferences and meaningful transitions; unchanged or merely blocked
  context is quiet. Alerts include dates, evidence, margin, horizon and open risks.
  Delivery is the private dashboard inbox only; no messages were sent externally.
- Prefect daily 06:00 and Sunday 07:00 Asia/Kolkata schedule definitions are tested.
  No continuously running scheduler, restart/durability proof or hosted deployment
  is claimed. All temporary verification servers were stopped.
- Weekly workflow tracks readiness or baseline evaluation. Real learned retraining,
  model calibration/promotion, drift monitoring and validated weekly model value
  still require suitable outcomes and historical release vintages.
- Eleven private tables have PostgreSQL tenant policies. Runtime accounts must be
  NOSUPERUSER NOBYPASSRLS; migration/Compose administrator credentials bypass RLS.
  Pilot static-token auth is not SSO/MFA or a production security audit.
- No licensed live price/freight/FX feed, full sanctions screening, comprehensive
  destination-rule monitoring, production object storage or complete source coverage
  has been verified. The generic event-provider adapter has no verified live LLM.

See PHASE4.md for setup, UI source attribution, artwork/prompt, commands and precise
limitations. Older phase documents retain their own implementation/evaluation context.
