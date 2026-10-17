# Phase 3: commercial intelligence backend

Implemented locally: conditional quotation accounting, human-reviewed legal/risk
evidence, a tenant-private decision API, and a pluggable text-event extraction pipeline.
This is a tested backend slice, not a deployed commercial radar. No real opportunity
is currently cleared. Phase 2's missing daily outcomes and unvalidated models remain
open; adding commercial accounting does not resolve forecasting performance.

## Run and demonstrate

From the repository root, using Python 3.12 and uv:

```powershell
uv sync --locked --group dev
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv run python -m src.cli init-local
uv run python -m scripts.demo_commercial
uv run python -m scripts.smoke_api
uv run uvicorn apps.api.main:create_app --factory --host 127.0.0.1 --port 8000
```

`init-local` adds missing SQLite tables and seeds references without inventing trade
observations. Existing stored forecasts remain intact. PostgreSQL uses
`uv run alembic upgrade head` and `uv run python -m src.cli seed` instead.
Open <http://127.0.0.1:8000/docs> for request schemas and Bearer authorization.

The demo is explicitly **SYNTHETIC — ILLUSTRATIVE, NOT A LIVE SIGNAL**. Hypothetical
20-tonne CIF accounting gives USD 450/tonne and USD 9,000/shipment, but missing legal
evidence blocks the score and forecast confidence stays null. It writes no quotes to
the database and calls no network service. These are fixture arithmetic, not actual
prices, forecasts, commercial margins or evidence of model value.

On Windows, `uv run python -m scripts.portable_postgres --test` creates a separate
loopback-only PostgreSQL cluster from the official vendor binaries. It runs all tests,
migration/schema comparison, restricted-role RLS checks, two real historical trade
imports, forecast-context persistence, and actual Uvicorn HTTP smoke checks. It stops
the server afterward and installs no service. Local trust authentication is confined
to this isolated test cluster. Test data and binaries stay in ignored `data/`.

## Accounting contract

- Decimal arithmetic; explicit kg, tonne or fixed-shipment basis; eight declared
  currencies. Foreign currency requires a verified direct FX quotation with rate date,
  availability, validity and source. No guessed rates, inversion or triangulation.
- Procurement, processing, packaging, certification, inland transport, origin port,
  export clearance, freight, insurance, destination transport, import clearance,
  duties, taxes, unloading, financing and other costs each appear exactly once.
  Seller-paid categories require an evidenced amount, including explicit zeroes.
- FOB, CFR, CIF, DAP and DDP have conservative supported payer templates. Maritime
  terms require sea transport; nonstandard allocations require contract review and
  re-quotation. These templates are not a complete Incoterms or tax engine. Tariffs
  are supplied reviewed amounts, not automatically retrieved or classified duties.
- Every selling/cost line and the bundle have quoted_at, published_at and expires_at.
  Future/expired inputs produce NOT_CALCULATED. To rank, validity must cover the
  selected 7/14/28-day window. Fixed shipment costs use the quoted quantity; lower
  buyer, stock or transport capacity requires a new quotation, not silent resizing.
- Margin = net selling quote minus seller costs in the reporting currency. Shipment
  profit = margin times quoted tonnes when fully feasible. Buyer costs are listed
  but excluded from seller accounting. Discounts must already be reflected in the
  selling quote; financing and taxes must be supplied explicitly.

## Decision contract and evidence

DGFT, destination import, SPS/certification and sanctions gates execute before score
calculation. Missing, conflicting, expired, unreviewed or unavailable evidence blocks
the score. A known ban starting within the shipping window overrides allow evidence.
Historical exports cannot supply any legal gate. Review snapshots exclude records
created after the decision origin, preserve independent conflicting rules, and version
revisions by appending new records rather than changing past decisions.

Reviewers must supply an exact source excerpt, dates, applicability, product/destination
and exact eight-digit ITC code matching the catalogue. Sanctions and certification
reviews are scoped to a quotation; sanctions review notes identify both buyer and
carrier references. Human reviewers must verify all applicable sanctions regimes,
counterparties, licences and certificates outside this software. A UN page or a source
URL alone is insufficient legal screening. There is no live sanctions-list matching.

Official text snapshots are bounded to 1 MB and HTTPS allowlisted hosts. Redirects,
query credentials, unsupported PDF bodies and empty text fail closed. Raw bytes,
checksums, first-observed availability and retrieval dates are retained locally;
24-hour cache hits retain their original availability. Policy decisions require a
source snapshot no more than 24 hours old and an unexpired reviewer attestation.
The underlying policy effective interval must cover the full shipping window.

Destination authority mappings currently cover only Saudi SFDA and US APHIS; these
host mappings are not proof that either source covers every product or requirement.
Other destinations stay unverified. Most catalogue entries are HS headings, not exact
ITC lines, and remain blocked. Basmati's source-reported code is not a validated full
ITC-edition catalogue. Broader mapping and legal review remain required.

Payment and logistics indicators are explicitly reviewed LOW/MEDIUM/HIGH/UNVERIFIED
inputs with citations and validity. They are not calibrated country-risk statistics.
Missing, expired, HIGH or UNVERIFIED risk evidence blocks scoring. Quote/capacity
review, positive quoted margin, matching validated demand and calibrated confidence
are also required. Public baseline contexts currently cannot satisfy these conditions.

The configurable weights in `configs/scoring.yaml` remain starting assumptions:
0.25 demand, 0.20 Indian supply, 0.30 profit, 0.15 accessibility, 0.10 confidence.
Complete 0–100 components require an explicit analyst normalization rationale bound
to the matching prediction. Confidence must match that prediction's calibrated
confidence. Components are not automatically learned or statistically validated.
The response shows score, currency/tonne and shipment margin, and forecast confidence
separately, with evidence dates/URLs, accounting assumptions and required next actions.
A score never demonstrates shipment success.

## Private API and authentication

All routes below are under `/api/v1/commercial`:

| Route | Roles and purpose |
|---|---|
| POST /quotes | exporter/admin: append a quotation |
| GET /quotes, /quotes/{id} | tenant readers: own quotes and accounting |
| POST /quotes/{id}/review | analyst/admin: append a reviewed quote version |
| POST /documents/fetch | analyst/admin: archive official source text |
| GET /documents/{id} | tenant readers: archived metadata and exact source text |
| POST /policies/review, /risks/review | analyst/admin: source-backed human attestations |
| GET /policies, /risks | tenant readers: review records |
| POST /events/extract | analyst/admin: validated text interpretation only |
| GET /events | tenant readers: unverified extracted events |
| POST /evaluate | exporter/admin: persist a full conditional decision |
| GET /decisions/{id} | tenant readers: immutable decision explanation |
| GET /audits | tenant admin: write audit records |

Set `AGRI_AUTH_CREDENTIALS` to a JSON object mapping lowercase SHA-256 digests of
strong random Bearer tokens to `tenant_id`, `actor_id`, and `roles` metadata. Example
shape (replace the placeholder with an actual digest; do not use it as a token):

```json
{"<64-character-lowercase-sha256-digest>": {"tenant_id": "your_company", "actor_id": "your_user", "roles": ["admin"]}}
```

Keep tokens secret and environment configuration outside version control. Only
`.env.example` is tracked; Python does not automatically load `.env`. Restart to
reload credential changes. Empty configuration closes private endpoints; there is no
default account. This is a static pilot token registry, not SSO, MFA, token expiry,
rotation automation or a production identity service. Put deployment behind TLS and
an appropriate identity/rate-limiting gateway before external use.

Tenant identity comes only from authentication, never request payloads. Administrators
are scoped to their own tenant. Reads filter ownership; missing and foreign records
both return 404. Composite foreign keys prevent cross-tenant document/quote references.
PostgreSQL migration 0003 enables and forces RLS on all seven private tables, with
transaction-local `app.tenant_id`. Production runtime credentials must be a separate
`NOSUPERUSER NOBYPASSRLS` role with only SELECT/INSERT on private tables, SELECT on
public reference/prediction tables, no schema ownership and no UPDATE/DELETE rights.
Use a different migration/initialization account. Superusers bypass RLS, including
the convenience Compose initialization account. SQLite verifies application filters
only and has no RLS. These checks are not a production security audit.

Successful writes commit an audit record atomically. Authenticated rejected POSTs
record path/status without tokens or bodies; unauthenticated attempts have no tenant
audit identity. Concurrent duplicate record conflicts return 409. No mutation or
deletion endpoint exists. Database administrators can still modify records; this is
not a cryptographically tamper-proof audit ledger. Private quotes never enter public
forecast responses or LLM requests.

## Text-event extraction

Document text is retrieved using lexical chunk ranking, then passed through the
`EventProvider` protocol. `EVENT_EXTRACTOR_ENDPOINT` and optional
`EVENT_EXTRACTOR_API_KEY` configure a generic HTTPS JSON service, not a turnkey vendor
SDK. The service receives `task`, `instruction`, `chunks`, `source_url`, `available_at`,
allowed product/country IDs and a JSON event schema, and must return only
`{"events": [...]}`. It must itself call the chosen model and adapt its output.
No live provider has been configured or verified. Tests use an explicitly SYNTHETIC
provider; missing configuration returns 503.

Events require a known product/country, bounded confidence, timestamps, exact source
URL and an exact supporting quote from retrieved chunks. Quantities, prices, yields,
forecasts and extra fields are rejected. Event confidence is extraction confidence,
not forecast probability. Deduplication uses product/country/type/date/direction;
distinct same-day events sharing that tuple can collapse. Every extracted event
remains UNVERIFIED and cannot create an approved policy rule. Semantic embeddings,
cross-source fact verification and robust prompt-injection evaluation remain future
work. Instruction and schema checks do not prove an LLM's interpretation is correct.

## Measured checks and live source probes

The final local verification results are recorded in [STATUS.md](STATUS.md). Tests
include currency/basis arithmetic, Incoterm allocation, unavailable/expired lines,
capacity, future review leakage, legal bans, prediction horizon matching, RBAC,
cross-tenant reads/references, database RLS, citation rejection, source boundaries,
raw corruption, cache vintage preservation, and event duplicate handling.

Executed on 2026-10-15:

- `uv run python -m scripts.fetch_evidence https://www.aphis.usda.gov/plant-imports`
  retrieved 1,879 characters of actual text, archived raw SHA-256
  `ed7a7ed1cb94d099df33d1f252122920c83e85a43f7b523392e0953adbdd5f45`, and returned
  UNVERIFIED. It is a general information page, not a commodity import clearance.
- APEDA's `https://apeda.gov.in/dgft-notifications` exceeded the 1 MB limit; no policy
  interpretation was produced. The UN consolidated-list page returned no substantive
  text through this client. Neither is treated as a functioning legal feed.

`scripts.fetch_evidence` prints structured UNVERIFIED failures with a nonzero exit
status. A successfully fetched document still requires source-specific applicability
review. PDF parsing, DGFT notification monitoring, full destination rules, sanctions
screening, licensed tariffs/freight/FX/current prices, actual quote verification,
calibrated demand/supply models and prospective commercial outcomes are unresolved.
Phase 4's dashboard, workflow definitions, internal alerts and exporter feedback are
now described separately in [PHASE4.md](PHASE4.md); its live-data and deployment limits remain explicit.
