# Phase 2 — baseline forecasting and evaluation

The service separates forecasts from commercial decisions. Quantitative baselines work
on genuine daily observations; source-backed monthly history stays monthly context.
No LightGBM/XGBoost model has been trained or promoted. No live forecasting accuracy,
profitability, classifier calibration or ranking success is claimed.

## Run the current real-data demo

```powershell
uv sync --group dev
uv run python -m src.cli init-local
uv run python -m src.cli import-commerce --product basmati_rice --hs 10063020 --partner 682 --period 202501
uv run python -m src.cli comtrade --product rice --hs 1006 --reporter 156 --partner 000 --flow M --period 202401
uv run python -m src.forecasting.cli forecast
uv run python -m scripts.smoke_api
uv run uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000/docs>. On PostgreSQL run `uv run alembic upgrade head`
with DATABASE_URL set, then `uv run python -m src.cli seed` before ingestion.
For repeatable isolated PostgreSQL acceptance on Windows:
`uv run python -m scripts.portable_postgres --test`. This downloads the official
vendor archive when absent, creates a disposable loopback-only cluster, runs migrations,
tests, public-data imports and an HTTP smoke check, then stops the server. It installs
no service. Test-only local trust authentication is never a production configuration.

The two real monthly observations produce six stored context records, one for each
product/country/horizon. They are **UNVERIFIED — NOT A LIVE EXPORT SIGNAL**. Weekly
quantity, current price, margin, score, confidence and intervals remain null. Measured
months are old; source retrieval recency is not freshness of the underlying market.
No weekly demand is inferred from an Indian export observation.

## Implemented quantitative components

| Component | Behaviour |
|---|---|
| Last value | Constant last-known observed level |
| Seasonal naive | Exact same weekday/week or month/year reference; missing references reject |
| Seasonal mean | Average of at least two matching weekdays/months; no interpolation |
| Demand target | Sum of next 7/14/28 complete UTC calendar-day demand labels in tonnes |
| Price target | Price at the 7/14/28-day endpoint, explicit currency per tonne |
| Readiness | Explicit daily/monthly frequency, homogeneous series/units/currency, age limits |
| Evaluation | Chronological origins, origin-specific vintage snapshots, later truth cutoff |
| Metrics | MAE, WAPE and signed bias; empty/all-zero undefined values remain null |
| Intervals | Finite-sample conformal residual quantiles, only after enough known calibration data |
| Persistence | Model/config version, input hash, exact evidence IDs, origin and actual creation time |

`configs/forecasting.yaml` controls freshness, minimum history and calibration settings.
It is validated and hashed into each persisted context run. Context older than the
monthly freshness limit does not receive a quantitative seasonal forecast. A historical
origin run created now is labelled HINDCAST_CONTEXT, not passed off as a prospective
forecast. Old runs remain reviewable through `/api/v1/forecasts/{prediction_id}` and
`/api/v1/opportunities/{prediction_id}`. API reads never write or recompute predictions.

No monthly disaggregation is allowed. A monthly row cannot be relabelled daily by
the model. Annual trade/production context also cannot manufacture daily training labels.
Prices require actual price series: the engine never turns customs value/quantity
into a destination wholesale quote. FX conversion is not performed implicitly.

## Run a real baseline evaluation

Provide one homogeneous daily series per product/destination/grade/provider. The
canonical CSV has exactly these headings:

```text
series_id,event_date,published_at,value,unit,currency,revision,source_url,frequency,synthetic
```

Use `tonne` with blank currency for demand, or `currency/tonne` plus an explicit
three-letter currency for prices. `frequency` must be `daily`, `published_at` must
include timezone, and `synthetic` must explicitly be `true` or `false`. Every source
must be reviewable. Historical availability must have genuine evidence; today’s
retrieval date cannot be backdated. Use a different series_id for different providers,
grades, Incoterms or dimensions. Mixed series/currencies/provenance reject.

```powershell
uv run python -m src.forecasting.cli backtest --csv verified-daily-demand.csv --target demand --origins 2025-03-01T00:00:00Z 2025-03-08T00:00:00Z --evaluation-cutoff 2025-06-01T00:00:00Z --output data/backtests/demand.json
```

The report evaluates all three baselines separately at each horizon, records skipped
folds, individual forecasts, training-snapshot hashes, input-file checksum and
configuration. Future labels are used only as truth, never as origin features.
Missing future daily labels skip that fold rather than become zero. Run separate
reports by product, destination and availability regime. Undefined metrics are null.

For a functioning CLI demonstration with entirely labelled synthetic inputs:

```powershell
uv run python -m scripts.demo_backtest
```

Files and reports are named SYNTHETIC and stored under `data/SYNTHETIC-demo`.
A perfect seasonal match on that constructed pattern is a correctness test, not
evidence of forecasting value. No synthetic report is shown as live performance.

## Weather, events and eligibility

NASA POWER daily UTC temperature/rainfall acquisition is implemented with caching,
retries, raw evidence, parameter/unit checks and missing-value rejection. A missing
rainfall measurement is never filled with zero. Original publication vintages are
unavailable, so new downloads use first-observed availability.

```powershell
uv run python -m src.ingestion.weather --latitude 19.9975 --longitude 73.7898 --start 2025-01-01 --end 2025-01-07 --output data/weather/nasa-point-context.json
```

This is a configured geographic point, not a verified crop production region.
Weather is emitted as an audited context JSON artifact; a PostgreSQL weather feature
store and trained weather-to-demand relationship are not implemented. The model does
not consume that artifact automatically. Time-aware feature selectors for weather
forecast issue/publication/valid times and verified active structured events are
tested. No live event feed, RAG or LLM provider is configured in Phase 2.

[NASA daily API documentation](https://power.larc.nasa.gov/docs/services/api/temporal/daily/)
documents UTC and source/grid request limits. No repeated full-grid polling is done.
[Open-Meteo commercial access](https://open-meteo.com/en/pricing) requires appropriate
commercial access; no free-tier production connector is silently enabled here.

The score implements the specified 0.25/0.20/0.30/0.15/0.10 weights in scoring.yaml,
strict [0,100] range validation and missing-input rejection. It runs only after all
DGFT, destination import, SPS/certification and sanctions categories have applicable,
verified evidence for the complete window. Any ban, unknown or expired requirement
blocks the score. No current legal-source ingestion exists yet, so every current
candidate is blocked. Scoring tests use explicitly synthetic evidence. This is a
transparent unvalidated score, not proof of export success.

## Remaining Phase 2 performance gate

The implementation is testable and runs against real PostgreSQL and source samples.
**Real weekly forecasting performance remains unmeasured.** Daily demand outcomes,
licensed destination prices, meaningful target definitions, adequate history and
historical publication vintages are absent. A classifier/boosted model, calibrated
probabilities and weather/event effects cannot be justified from two monthly rows.
Source-grade backfills and a prospective daily-outcome collection period are needed.
Only after baseline measurement should success thresholds and ML promotion criteria
be chosen. No commercial ranking or Phase 3 cost/policy integrations are claimed.
