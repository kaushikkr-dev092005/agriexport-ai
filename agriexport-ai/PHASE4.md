# Phase 4: local pilot, dashboard, automation and outcomes

The local software pilot is implemented. This is not a completed prospective
exporter trial, a validated weekly forecasting model, or a production deployment.
No live export opportunity is cleared by the current source data.

## Open the finished local app

From `agriexport-ai` in PowerShell, the current checkout already has the built UI:

```powershell
uv run python -m scripts.preview
```

The launcher opens loopback-only services and prints:

- Landing: <http://127.0.0.1:3000/>
- Dashboard: <http://127.0.0.1:3000/dashboard>
- Typed API docs: <http://127.0.0.1:8000/docs>

Press Ctrl+C to stop both services. It adds missing local SQLite tables without
inventing observations, does not install a service, and refuses occupied ports.
Use `--api-port` / `--dashboard-port` to choose different ports. Logs remain in
ignored `data/preview-*`. `--smoke` verifies HTTP readiness and stops the servers;
the browser suite below verifies actual user interactions.

## Clean setup and builds

Python 3.12, uv and Node 22 are used. If Node is missing on Windows, the included
helper downloads the official Node LTS archive, verifies its published SHA-256,
and extracts it only beneath ignored `data/tools/node`:

```powershell
uv sync --locked --group dev --extra automation
uv run python -m scripts.setup_node
$env:Path = "$PWD\data\tools\node;$env:Path"
uv run python -m src.cli init-local
uv run python -m src.forecasting.cli forecast
Set-Location apps/dashboard
npm.cmd ci --no-fund --no-audit
$env:NEXT_TELEMETRY_DISABLED = '1'
npm.cmd run typecheck
npm.cmd run build
Set-Location ../..
uv run python -m scripts.preview
```

Skip `setup_node` and the PATH adjustment when an appropriate system Node is already
installed. The initial database contains reference data only; empty trade/results
states are intentional. Phase 1/2 documentation gives explicit genuine historical
sample import commands. New data never becomes a live signal by being ingested.

For frontend development, start FastAPI from the repo root in one terminal:

```powershell
uv run uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

In another terminal, with Node on PATH, run `npm.cmd run dev` from `apps/dashboard`.
`AGRI_API_ORIGIN` configures the server-side proxy (default 127.0.0.1:8000).
`AGRI_DASHBOARD_ORIGIN` may specify an exact public origin behind a trusted proxy;
otherwise writes must match the incoming Host and protocol. No shared server-side
Bearer token is injected. Tokens, API keys and database URLs are never frontend
`NEXT_PUBLIC_*` settings. Python does not automatically load `.env`.

PostgreSQL requires `DATABASE_URL`, `uv run alembic upgrade head`, and reference
seeding before startup. Migration 0004 adds four private pilot tables and composite
decision references. Use a migration administrator separately from a runtime role
with NOSUPERUSER NOBYPASSRLS and the necessary SELECT/INSERT privileges. Grant the
new tables to an existing runtime role after migration. The Compose file still
starts the database only; no containerized full-stack deployment is claimed.

## Landing page and UI components

`/` is the editorial landing page inspired by the warm neutrals, generous spacing,
landscape imagery and restrained typography in
[Office Commun's Figr project](https://officecommun.com/projects/figr).
It uses genuine Aceternity UI registry components: Bento Grid, Hover Border Gradient
and Text Generate Effect. These are vendored in `components/ui` and use Tailwind v4
and Motion. Source URLs/checksums are in `apps/dashboard/aceternity-sources.json`;
attribution and applicable terms are in `apps/dashboard/THIRD_PARTY_NOTICES.md`.
No paid template, Figr artwork, brand assets or copy were incorporated.

The generated landscape is decorative, not documentary imagery or market evidence.
The built-in image tool produced `apps/dashboard/public/agri-landscape.png`; its full
prompt is saved in `apps/dashboard/ARTWORK.md`. The interactive concept preview is
labelled ILLUSTRATIVE, NOT A LIVE SIGNAL, with unknown quantities/margins left unknown.
Navigation, FAQ disclosure and workspace links work on desktop/mobile. Reduced
motion is supported. Marketing copy states the pilot's evidence and validation limits.

## Four dashboard views

1. Opportunity radar: stored product/country/horizon contexts, 7/14/28-day filters,
   search, category filtering, sorting, blocked-item visibility and an evidence
   drawer with source dates, risks and verify-before-quoting actions. Public baselines
   are currently blocked; there are no substituted demonstration forecasts.
2. Country intelligence: reference map, market selector and historical sample coverage.
   Production, import dependence, current suppliers and access stay unverified.
3. Commodity intelligence: source HS mappings, observed trade quantities/value and
   sample history bars. Supply and current/competitor prices stay unverified. Customs
   value is never labelled a selling quote or wholesale price.
4. Evidence and alerts: observation/availability/retrieval ledger, private commercial
   decision explanations, dashboard alert inbox, preferences, feedback and run history.

Reference geography is bundled Natural Earth public-domain data, with provenance in
`public/map-source.json`. It is not a demand heatmap. Historical samples may overlap
in product, reporter, flow or currency and are not silently aggregated.

## Private workspace and feedback

The existing environment token registry and exporter/analyst/admin roles apply.
The browser holds a user-entered token in tab memory; it clears on disconnect/reload.
It does not write credentials to localStorage/sessionStorage. Requests use a fixed
upstream and an explicit proxy route allowlist. Cross-origin writes are rejected;
FastAPI independently verifies Bearer roles and tenant ownership. This is pilot
authentication, not SSO, MFA or a production security audit.

Configure `AGRI_AUTH_CREDENTIALS` in the terminal that launches the API. Shape and
strong-token guidance are in [PHASE3.md](PHASE3.md). Do not use the browser tests'
SYNTHETIC credentials as actual accounts. Public research requires no token.

New authenticated API routes:

| Route | Behaviour |
|---|---|
| POST /api/v1/feedback | Exporter/admin self-reported inquiry, quote, won, lost or shipped outcome |
| GET /api/v1/feedback | Own tenant's immutable outcome records |
| POST /api/v1/alert-subscriptions | Append preference or disable a product/market/horizon/currency scope |
| GET /api/v1/alert-subscriptions | Own preference history |
| GET /api/v1/alerts | Own internal material-change inbox |
| GET /api/v1/pipeline-runs | Own refresh counts, outages and blocked share |
| GET /api/v1/commercial/decisions | Own conditional assessments for review/outcome linkage |
| POST /api/v1/commercial/quotes/{id}/revision | Append changed quote under original lineage; reset approvals |

Feedback requires an owned decision, idempotency key, evidence reference and event
date. An event may neither be in the future nor predate the stored decision.
Repeated identical idempotency keys return the same record; changed payloads conflict.
Shipment actuals require explicit tonnes, reporting currency, revenue and total seller
cost; arithmetic produces self-reported realised profit/margin. These remain
SELF_REPORTED_UNVERIFIED, distinct from audited commercial results. No conversion,
shipment-success rate or profitable-opportunity-rate claim is inferred from fixtures.

The four new tables have tenant policies and composite decision references. Writes
and success audits commit atomically; authenticated rejected writes are audited.
Existing decisions and quotations are not overwritten. A cost revision resets analyst
approval and may require new shipment-specific policy/certification reviews.

## Daily flow, schedules and material alerts

Install `--extra automation` to run Prefect/MLflow workflows. One-shot commands:

```powershell
uv run --extra automation python -m pipelines.daily_refresh
uv run --extra automation python -m pipelines.weekly_retraining
```

`configs/pipeline.yaml` lists explicit Commerce/Comtrade source jobs. The default
empty list reports NOT_CONFIGURED and a DEGRADED refresh, not a successful live feed.
Jobs invoke existing audited connectors with validated arguments and bounded timeouts;
failed sources remain unverified. No wildcard bulk scraping/backfill is enabled.

Daily processing ingests/validates configured public jobs, persists baseline context,
then evaluates latest real quotation versions per configured tenant and 7/14/28-day
window. Legal/commercial gates and scoring precede alerts. Synthetic quotations are
excluded. Source outages, errors, counts and blocked share are retained in tenant
run history. Empty denominators stay null. No private amounts appear in global run
summaries. Missing feed jobs and tenant credentials are explicit configuration gaps.

Alerts require an enabled matching subscription and a material transition: new
eligible conditional decision, crossing the user's margin threshold, a sufficiently
large supported demand forecast shift, or legal eligibility invalidating a prior
recommendation. The default configurable forecast-change fraction is 20%, an
operational preference, not an empirically validated threshold. Margin comparisons
require the same currency. No alert fires merely because a new blocked baseline was
stored. Unchanged re-evaluations are quiet; identical alert writes are deduplicated.
Each alert carries decision/evidence references, dates, margin, horizon and open risks.

**Delivery is the private dashboard inbox only.** There is no configured email, SMS,
Slack or webhook transport, and no message was sent to anybody.

`pipelines.serve` defines daily 06:00 and Sunday 07:00 Asia/Kolkata deployments with
concurrency limits. To operate unattended, provision a Prefect server and keep the
serving process alive under your own process supervision. For a local terminal setup:

```powershell
# Terminal A, after installing the automation extra:
uv run --extra automation prefect server start --host 127.0.0.1
# Terminal B, from the repo root:
$env:PREFECT_API_URL = 'http://127.0.0.1:4200/api'
$env:PREFECT_SERVER_ANALYTICS_ENABLED = 'false'
uv run --extra automation python -m pipelines.serve
```

Schedule construction and timezone definitions are tested; continuous unattended
operation, restarts and deployment are not validated. One-shot flows have actually run
through local temporary Prefect servers, which were stopped afterward. No long-running
scheduler or OS service was installed or left running by this implementation.

## Weekly readiness and MLflow

No verified daily outcomes are configured, so a real tracking run records
SKIPPED_DATA_NOT_READY and no fabricated metrics/model. `MLFLOW_TRACKING_URI` defaults
to `sqlite:///data/mlflow.db`; local artifacts are ignored. If explicitly supplied a
canonical daily CSV, chronological origins and cutoff, the workflow evaluates the
existing baselines and logs measured horizon-specific metrics plus its input hash.
Synthetic series retain SYNTHETIC provenance in reports and tracking tags.

This workflow is readiness/baseline evaluation, **not learned-model retraining**.
No LightGBM/XGBoost candidate is fitted, no classifier calibrated, and no model is
promoted. Actual retraining/drift/performance gates still require appropriate outcomes,
historic vintages, prospective quotes and independent realised shipment verification.

## Executed acceptance

Current results are in [STATUS.md](STATUS.md). Re-run:

```powershell
uv run --extra automation pytest -q
uv run --extra automation ruff check .
uv run --extra automation ruff format --check .
uv run --extra automation python -m scripts.portable_postgres --test
# With Node on PATH, in apps/dashboard:
npm.cmd run typecheck
npm.cmd run build
npm.cmd run test:e2e
```

The Playwright suite uses installed Microsoft Edge on Windows. Change its browser
channel or provision a browser for other environments. Its dedicated API copies
genuine public local samples into a disposable SQLite database and injects only
SYNTHETIC private credentials, quotes and outcomes; it never writes to the operator's
database. Browser coverage includes all four views, source drawer, filters, outage
handling, private shipment accounting, tenant switching, credential storage, proxy
restrictions, landing navigation/FAQ, desktop/mobile and reduced motion. Screenshots
live under ignored `data/screenshots/` and were visually inspected. These functional
checks are not production, security, profitability or forecasting-performance evidence.
