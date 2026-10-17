# Implementation blueprint and phase gates

Current status is in [STATUS.md](STATUS.md). Phase 1 runs on real source samples and
PostgreSQL; the Phase 2 baseline/evaluation service is implemented. [PHASE2.md](PHASE2.md)
separates working components from unmeasured forecasting performance. Phase 3's
commercial backend is implemented within the limits in [PHASE3.md](PHASE3.md);
live policy clearances, calibrated demand and commercial outcomes remain open gates.
Phase 4's local UI, internal alerts, feedback and workflow definitions are implemented
within the limits in [PHASE4.md](PHASE4.md). No prospective exporter trial or continuous
unattended deployment is claimed. Remaining integration/promotion requirements follow.

## Architecture

Modular monolith: ingestion → validation / HS mapping / availability / anomaly checks
→ demand, supply, event, price/cost models → hard eligibility gates → transparent
ranking → API, dashboard and material-change alerts. Demand estimates do not imply
Indian export feasibility. Unsupported quantities, prices and margins stay null.

PostgreSQL is the source of record. Object storage will retain immutable source
responses/news and signed retrieval manifests; Phase 1 provides a local adapter.
Every derived output will carry event date, availability date, creation time, model
version, training cutoff, source revisions and configuration hash. Every query and
feature uses `published_at <= forecast_origin`; revised observations are selected
within that cutoff, never backfilled from today's revised values.

## Phase 1 — data foundation

Catalogue and exact HS-level mappings, canonical Indian export imports, Comtrade
connector, raw archival, strict validation, SQLAlchemy/Alembic and read-only trade
explorer. Acceptance: tests pass; real reviewed Indian source sample round-trips;
Comtrade live response is validated and archived; PostgreSQL migrations execute;
publication provenance is audited. Missing live samples are external acceptance
blockers, not permission to substitute fixtures. Partial local completion is stated
explicitly in STATUS.md. No later phase begins before the gate is met.

## Phase 2 — forecasting and measurement

Add individual adapters with raw archival, retries, cache, typed schema and source
configuration notes only after verifying endpoint formats and licence:

| Source | Role | Planned configuration / unresolved issue |
|---|---|---|
| USDA PSD/FAS | Stocks, production, competing supply | Official FAS API credentials and current schema verification required |
| FAOSTAT | Annual structural production context | Verify official bulk file versions and release dates; never weekly targets |
| Open-Meteo | Region-specific weather nowcast/forecast | Verify commercial licence, forecast issue times and historical runs |
| NASA POWER | Weather history/anomalies | Verify parameters, units and data availability lag |
| OGD/AGMARKNET | Mandi arrivals and procurement prices | OGD key/resource ID, market quality/grade and unit mapping required |
| Licensed destination prices / FX | Price and conversion inputs | Licensed feed, quote basis, observed/published times and FX rate date required |
| Exporter/freight quotations | Executable costs and shipment limits | Tenant-scoped authenticated inputs, expiry, Incoterm and route required |
| ITC Market Access Map | Tariff context | Licensed access and origin/destination/product/date conditions required |
| DGFT / destination authorities | Eligibility evidence | Reviewed current official documents, exact ITC(HS), expiry and provenance required |
| Tenders / buyer leads / events | High-frequency demand evidence | Source permission, authenticity, duplicates and availability checks required |

These are a source integration plan, not verified live feeds. No connector for them
is advertised as working in Phase 1.

Demand A: establish monthly last-value, seasonal-naive and basic seasonal statistical
baselines per product/destination. Add LightGBM/XGBoost only after chronological
evaluation can beat those baselines. Train a meaningful-demand-rise classifier and
volume regressor only when observable targets support the intended horizon. Monthly
trade cannot be divided by four to manufacture weekly labels. Without weekly actuals,
publish seasonal context with low confidence and null 7/14/28-day volume.

Supply B: commodity plugins begin with inventory balance (production + opening
stocks − domestic consumption − required reserves − existing commitments), constrained
by arrival data, harvest calendars and logistics. Never label national production
as exporter inventory. All required components must be observed or explicitly unknown.

Price D: price baselines by grade/market/Incoterm; quantile forecasts only with enough
history. Features include lagged prices/trade, seasonality, arrivals, weather runs
known at origin, FX, dated stock estimates and verified buyer evidence. Fit transforms
on training folds only. Do not mix overlapping HS aggregates or distinct currencies.

Evaluation is built before model claims: expanding/rolling chronological folds with
purge gaps covering horizon/label delay. Reconstruct snapshots separately for each
origin and 7/14/28-day horizon. Future observations are evaluation labels only; do
not use those releases as features. Score product, destination and availability
segments separately. Metrics: MAE/WAPE/bias, PR-AUC/precision/recall/calibration,
interval coverage/width. Undefined denominators are reported, not filled with zero.
Confidence must derive from out-of-time calibration and feed coverage, separate
from opportunity score. Set thresholds only after measuring baselines. No invented
historical performance or synthetic improvement claims.

## Phase 3 — commercial intelligence

Eligibility first: DGFT export status, destination import rules, SPS/phytosanitary
requirements, certificates and sanctions must all have applicable, current, verified
evidence for exact product, origin, destination and window. Any deny/unknown/expired
status returns BLOCKED_OR_UNVERIFIED, reasons and null score. A general country score
cannot override a gate. Human review and evidence validity are versioned.

Cost accounting records currency, mass/quote unit, FX rate/date/source, Incoterm,
shipment size, route, expiry, taxes and who pays each leg. Delivered cost per tonne
= procurement + processing + packaging + inland + port + freight + insurance +
financing + seller-paid duties/taxes. Margin = net selling price − delivered cost;
profit = margin × feasible shipment tonnes. Missing any required cost or selling quote
means margin is not calculated. Reject double-counted Incoterm legs. Feasible tonnes
are the minimum of buyer volume, verified exporter stock and logistics capacity;
zero/negative margins cannot be presented as profitable opportunities.

Ranking E: use configs/scoring.yaml (0.25 demand + 0.20 Indian supply + 0.30 profit +
0.15 accessibility + 0.10 confidence). Validate finite inputs in [0,100], weight
sum and required components; never impute missing scores. Gate before computing.
Display score, margin (currency/tonne and shipment) and forecast confidence separately.
Test every gate, unknown/expired evidence, invalid score ranges, FX units and Incoterms.
Learning-to-rank waits for genuine outcomes; transparent weights remain assumptions.

Event C follows the tested pipeline: pluggable LLM extracts product, country, event
date, impact direction, source URL, confidence and expiry. Retrieval uses allowlisted
official sources, deduplication, content hashes and rule validation. Include publication
time, citation spans and reviewer state. LLM text is untrusted; never accepts generated
statistics, yields, prices or forecasts as quantitative evidence. RAG must enforce
availability cutoffs and resist source-text instructions. No LLM provider is configured.

Decision evaluation simulates rankings with costs, rules and prices known at each
origin. Measure Precision@K, NDCG@K, profitable-opportunity rate, margin MAE/tolerance
share and uncertainty coverage. Real executable quotes are required for profit labels.

## Phase 4 — prospective pilot

Next.js/React/TypeScript views: opportunity radar; country intelligence; commodity
intelligence; evidence/alerts. Use real evidence or empty states. Illustrations carry
ILLUSTRATIVE, NOT A LIVE SIGNAL. Cards show unresolved risks, assumptions, freshness,
sources and verify-before-quoting actions (policy, destination rules, prices, stock,
freight). Trade history may show a chart but cannot masquerade as demand forecast.

Add typed versioned forecast, opportunity detail, markets, events and feedback APIs.
Before writes: identity provider, RBAC, per-tenant database policies and repository
filters, audited access and writes, negative cross-tenant tests. Private quotes never
enter global training/features without explicit permission and segregation controls.

Add production, price, weather, event, policy, tenant quote, prediction and audit tables
through Alembic. Each observation carries event/availability/revision fields; weather
also carries issue/run time and valid time. Predictions store forecast origin/horizon,
model version, data snapshot/config hashes, interval, confidence and nullability reasons.
Later add shipments, buyer leads, feedback and realised outcomes.

Prefect daily flow: ingest → quarantine invalid batches → freshness checks → snapshot
→ forecasts → all gates → rank → material-change alerts. Weekly MLflow-tracked training
promotes only measured candidates; an outage or regression retains prior model and
marks outputs stale. Idempotent alerts compare persisted previous state and fire for
new eligible opportunities, configured margin crossings, large forecast shifts and
policy invalidation. Include evidence, timestamp, horizon, margin and open risks.
No email/Slack recipients are contacted without explicit authorization.

Prospective pilot freezes forecasts before outcomes and records inquiries, quotes,
won/lost reasons, actual margin, conversion and shipment success. Monitor feed freshness,
outages, drift and share blocked for missing evidence. Expansion beyond pilot groups
requires measured benefit and legal/data coverage; success thresholds follow baselines.
