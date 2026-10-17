# AgriExport AI

Commercial export intelligence for India. **Phase 4 local pilot implemented**, with
a landing page, four dashboard views, private outcomes, internal alerts and workflows.
Quote-based margin accounting works; no trained ML model, validated live recommendation,
current legal approval, or realised profit is claimed.
Forecasting and commercial decision engines remain separate. Monthly customs history
is structural context; it cannot justify precise 7/14/28-day quantity predictions.
See [PHASE2.md](PHASE2.md) for baseline/evaluation commands, configuration and limitations.
See [PHASE3.md](PHASE3.md) for private quotation APIs, reviewed evidence, authentication,
PostgreSQL tenant isolation, the synthetic demo and remaining live-data gates.
See [PHASE4.md](PHASE4.md) for the Aceternity UI landing page, dashboard, Node setup,
automation, feedback and current limitations. No prospective commercial pilot is complete.
See [docs/TRUCK_GUIDE.md](docs/TRUCK_GUIDE.md) for the landing overlay, editable stops,
sample card values, accessibility behavior, asset TODOs and browser checks.

## Open the app

The dashboard is built in this checkout. From `agriexport-ai`:

```powershell
uv run python -m scripts.preview
```

Open <http://127.0.0.1:3000/> for the landing page and
<http://127.0.0.1:3000/dashboard> for the workspace. Ctrl+C stops both local services.
For a clean installation, rebuild, or missing Node/dependencies, follow [PHASE4.md](PHASE4.md).

## Run locally (PowerShell, Python 3.12 + uv)

```powershell
cd agriexport-ai
uv sync --locked --group dev
uv run pytest -q
uv run python -m src.cli init-local
uv run python -m scripts.demo_commercial
uv run python -m src.forecasting.cli forecast
uv run python -m scripts.smoke_api
uv run uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs>. The interactive OpenAPI explorer supports
`GET /api/v1/products` and `GET /api/v1/trade?product_id=rice&partner=682`.
`GET /api/v1/forecasts` returns persisted 7/14/28-day context and explanations;
`GET /api/v1/opportunities` exposes blocked candidates with missing evidence.
`as_of` must include a timezone. Rows retain original value currency; totals across
currencies or overlapping HS levels must never be silently summed. The local database
starts empty except for reference data. Synthetic rows are opt-in, visibly labelled.

### PostgreSQL

Docker Compose requires Docker and an environment password. These commands are for
your local terminal; `.env` files are not loaded by Python automatically.

```powershell
$env:POSTGRES_PASSWORD = '<choose-local-password>'
docker compose up -d postgres
$env:DATABASE_URL = 'postgresql+psycopg://agriexport:<url-encoded-password>@localhost:5432/agriexport'
uv run alembic upgrade head
uv run python -m src.cli seed
uv run uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

Production uses Alembic; `init-local` is deliberately SQLite-only. SQLite acceptance
tests do not prove PostgreSQL integration. Use an isolated PostgreSQL database for
deployment verification; never downgrade a populated production database casually.
For the private API, use a separate application role with `NOSUPERUSER NOBYPASSRLS`,
without schema ownership or migration privileges. The Compose initialization account
is an administrator and bypasses RLS; use it only for initialization/migrations.

## Ingestion configuration

Raw bytes are SHA-256-addressed files beneath `RAW_STORAGE_PATH` (default `data/raw`).
A retrieval manifest preserves URL, checksum and retrieval time. Database rows link
to the artifact. This is **local storage**, not a deployed object store. Retain and
back up manifests and artifacts together. No credentials are written into manifests.

### Indian history: APEDA and Department of Commerce

**Native Commerce adapter added:** `src/ingestion/commerce.py` reads the current public
MEIDB product-country form, joins exact monthly quantity/value columns, validates KGS
and USD-million units, and archives both parent reports with a lineage bundle. It
rejects blank HS4 quantity units. A real basmati report was imported successfully.
Source edition is labelled `ITC-source` (edition unverified), not guessed as HS2022.

```powershell
uv run python -m src.cli import-commerce --product basmati_rice --hs 10063020 --period 202501 --partner 682
```

This is a historical sample, not a current opportunity. Rounded USD-million source
values are scaled explicitly to USD and must not be treated as precise selling quotes.
Fresh form sessions, retries, 24-hour query caching and raw audit storage are implemented.

- [APEDA AgriExchange](https://agriexchange.apeda.gov.in/Home/) publishes trade reports.
- [Commerce monthly statistics](https://www.commerce.gov.in/ministryofcommerce/node/893)
  link to [TradeStat](https://tradestat.commerce.gov.in/).
- A current Commerce HTML form/schema is verified. A stable downloadable APEDA API/schema
  remains unverified. No invented API or automatic heading guessing is used.
- `src/ingestion/apeda.py` is a canonical CSV adapter for both reviewed source exports.
  An operator must preserve the official download and document transformations into
  the canonical CSV. It is **not** a native APEDA/Commerce report parser. The original
  official file must be retained alongside the transformed file by the operator;
  automatic lineage between those files is future work.
- Local file ingestion needs no retries or cache; immutable raw archival applies.

Canonical CSV headings:

```text
product_id,hs_code,hs_revision,reporter,partner,period,event_date,flow,quantity,quantity_unit,value,currency,published_at,availability_basis,publication_evidence_url,revision,synthetic
```

Use exact catalogue product/HS/revision mappings, M49 codes (India `356`), flow `X`,
period `YYYY-MM-01`, event date within that period, explicit `kg` or `tonne`, timezone
timestamps and a source revision. Do not use financial-year summaries as months.
Zero mass is valid but cannot support a unit price; missing mass/value is rejected.
`synthetic` must be `true` for test data. No example numbers are shipped as live data.

If publication is unknown, leave `published_at` empty and use `first_observed`; the
adapter assigns retrieval time. Historical `source_publication` requires an evidence
URL. A URL is evidence supplied by an operator, not automated verification of the
document's contents. Revisions are immutable; conflicts are rejected. Unknown country
codes fail pending reviewed reference-data expansion. A batch commits atomically.

```powershell
uv run python -m src.cli import-india --csv downloaded-and-reviewed.csv --source commerce --source-url https://tradestat.commerce.gov.in/
```

### UN Comtrade

[Official API documentation](https://uncomtrade.org/docs/un-comtrade-api/) documents
keyless preview endpoints and limits. The connector uses monthly commodity data,
`netWgt` in kg and `primaryValue` in USD, accepts only H6/HS2022, and archives responses
including failures. It retries transport/server failures three times with exponential
backoff, spaces requests, and stops on 429 showing `Retry-After`. Re-run after that
window. Cached successful queries expire after 24 hours; cached retrieval retains its
original availability timestamp. Preview cap responses fail rather than imply a
complete dataset. Narrow requests to a single product/partner/month.

```powershell
uv run python -m src.cli comtrade --product rice --hs 1006 --partner 682 --period 202401
```

The India rice query returned no rows; this does not establish zero exports. A nonempty
global import-demand sample was verified with:

```powershell
uv run python -m src.cli comtrade --product rice --hs 1006 --reporter 156 --partner 000 --flow M --period 202401
```

`COMTRADE_API_KEY` is optional; `COMTRADE_BASE_URL` can select an approved paid endpoint.
Only official HTTPS endpoints should be configured. This preview adapter is not a
bulk backfill client and does not reconstruct historic Comtrade publication vintages.
Historic backtesting before first retrieval requires actual archival publication
snapshots. Review source licences, commercial redistribution terms and your plan's
limits before production use. None are assumed by the code.

## Implemented boundaries

- Broad starter catalogue: all requested categories represented by 18 headings or
  subheadings; this is not an exhaustive all-SKU or ITC(HS) catalogue. Pilot groups are
  rice, onions, selected spice groups, fresh grapes and tea. Exact 8-digit legal mapping
  remains `unverified` for legal use. One additional source-reported ITC code for
  basmati brings the starter total to 19 products. Heading history does not establish eligibility.
  All 18 codes were checked against the official HS2022 reference; the evidence lives
  in `configs/catalogue_verification.json`. To repeat this explicit online metadata
  check and refresh source evidence: `uv run python -m scripts.verify_catalogue`.
- SQLAlchemy models and frozen Alembic migrations: products, countries, raw artifacts,
  immutable trade observations, predictions and seven tenant-private commercial tables.
  PostgreSQL 16.15 runtime and restricted-role RLS tests passed.
- Source-neutral schema, explicit mass conversion, currency preservation, temporal
  constraints, idempotency, version-aware snapshots, source-separated observations.
- Public FastAPI trade/forecast/context explorer and blocked opportunities; separate
  authenticated quotation, review, evidence, risk, event and decision APIs with tenant
  isolation and audit logs. Private endpoints fail closed without credentials.
- Demand/price baselines, chronological evaluation, conformal interval tools, eligibility-first
  scoring, weather/event feature contracts and a NASA POWER connector are implemented.
  NASA data is archived point-weather context; crop-region mapping/model use remains unverified.
- Quotation margin accounting, reviewed policy gates, source text archival and a pluggable
  text-event provider work. No live LLM provider, automated policy monitoring or current
  legal clearances have been verified. See [PHASE3.md](PHASE3.md) for supported boundaries.
- Next.js/React/TypeScript landing and dashboard, tenant-scoped feedback, internal
  material alerts, source/run status and Prefect schedule definitions are implemented.
  Weekly MLflow readiness/evaluation runs work; learned training/promotion is blocked.
  No live production/price feeds, unattended deployment, external notification delivery,
  measured ML improvement or executable weekly signal is claimed.

## Acceptance and subsequent work

`uv run pytest -q` exercises mass/currency validation, timestamp leakage, revision
snapshots, synthetic exclusion, transaction prevalidation, immutable conflicts,
mocked transport failures/retries/cache, API and Alembic upgrade/downgrade on SQLite.
Transport fixtures are SYNTHETIC. Live data and PostgreSQL checks are separate.
See [STATUS.md](STATUS.md) for executed results and unresolved acceptance gates, and
[ARCHITECTURE.md](ARCHITECTURE.md) for the remaining phased design and evaluation plan.
