"""Tenant-private commercial APIs. All mutations require roles and atomic audit records."""

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import Engine, select

from apps.api.auth import Principal, load_credentials, require_roles
from src.database.commercial_models import (
    AuditLog,
    CommercialDecision,
    CountryRisk,
    EvidenceDocument,
    ExportCostQuote,
    MarketEvent,
    PolicyRule,
)
from src.database.models import Country, Prediction, Product
from src.database.private_repository import append_record, owned, records, tenant_session
from src.forecasting.service import aware
from src.intelligence.commercial_schemas import (
    DecisionRequest,
    DocumentRequest,
    ExtractionRequest,
    PolicyReview,
    QuoteReview,
    RiskReview,
)
from src.intelligence.evidence import (
    DocumentFetcher,
    EventProvider,
    HttpEventProvider,
    TransientDocumentError,
    extract_events,
)
from src.intelligence.policy_checks import GateCategory
from src.ranking.commercial import decide
from src.ranking.profitability import ShipmentQuote, calculate_margin


def view(record) -> dict:
    """Private response, never included in public forecast payloads."""
    return {
        "record_id": record.record_id,
        "created_at": aware(record.created_at).isoformat(),
        "synthetic": record.synthetic,
        "label": "SYNTHETIC — ILLUSTRATIVE, NOT A LIVE SIGNAL"
        if record.synthetic
        else "PRIVATE TENANT RECORD",
        **record.payload,
    }


def create_commercial_router(
    engine: Engine,
    credentials=None,
    document_fetcher: DocumentFetcher | None = None,
    event_provider: EventProvider | None = None,
) -> APIRouter:
    """Dependencies are injectable; absent credentials/provider fail closed without side effects."""
    registry = credentials if credentials is not None else load_credentials()
    reader = require_roles(registry, {"exporter", "analyst", "admin"})
    writer = require_roles(registry, {"exporter", "admin"})
    reviewer = require_roles(registry, {"analyst", "admin"})
    administrator = require_roles(registry, {"admin"})
    router = APIRouter(prefix="/api/v1/commercial", tags=["Private commercial intelligence"])

    @router.post("/quotes", status_code=201)
    def add_quote(body: ShipmentQuote, principal: Annotated[Principal, Depends(writer)]) -> dict:
        with tenant_session(engine, principal) as session:
            if not session.get(Product, body.product_id) or not session.get(
                Country, body.destination
            ):
                raise HTTPException(422, "Unknown product/country reference")
            now = datetime.now(UTC)
            if body.published_at > now:
                raise HTTPException(422, "Quotation is not yet available")
            record = append_record(
                session,
                ExportCostQuote,
                principal,
                {"quote": body.model_dump(mode="json"), "review_status": "UNVERIFIED"},
                "quote.create",
                body.synthetic,
                product_id=body.product_id,
                destination=body.destination,
            )
            return view(record)

    @router.get("/quotes")
    def quotes(principal: Annotated[Principal, Depends(reader)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(r) for r in records(session, ExportCostQuote, principal)]

    @router.post("/quotes/{quote_id}/revision", status_code=201)
    def revise_quote(
        quote_id: str, body: ShipmentQuote, principal: Annotated[Principal, Depends(writer)]
    ) -> dict:
        """Append changed costs/capacity under the same lineage; all analyst approvals reset."""
        with tenant_session(engine, principal) as session:
            original = owned(session, ExportCostQuote, quote_id, principal)
            if original is None:
                raise HTTPException(404, "Quotation not found")
            if (body.product_id, body.destination, body.synthetic) != (
                original.product_id,
                original.destination,
                original.synthetic,
            ):
                raise HTTPException(422, "Revision must retain product, destination and provenance")
            if body.published_at > datetime.now(UTC):
                raise HTTPException(422, "Quotation is not yet available")
            return view(
                append_record(
                    session,
                    ExportCostQuote,
                    principal,
                    {
                        "quote": body.model_dump(mode="json"),
                        "review_status": "UNVERIFIED",
                        "original_quote_id": original.payload.get(
                            "original_quote_id", original.record_id
                        ),
                        "supersedes_quote_id": original.record_id,
                    },
                    "quote.revise",
                    body.synthetic,
                    product_id=body.product_id,
                    destination=body.destination,
                )
            )

    @router.get("/quotes/{quote_id}")
    def quote(quote_id: str, principal: Annotated[Principal, Depends(reader)]) -> dict:
        with tenant_session(engine, principal) as session:
            record = owned(session, ExportCostQuote, quote_id, principal)
            if record is None:
                raise HTTPException(404, "Quotation not found")
            result = view(record)
            result["accounting"] = calculate_margin(
                ShipmentQuote.model_validate(record.payload["quote"]), datetime.now(UTC)
            )
            return result

    @router.post("/quotes/{quote_id}/review", status_code=201)
    def review_quote(
        quote_id: str, body: QuoteReview, principal: Annotated[Principal, Depends(reviewer)]
    ) -> dict:
        with tenant_session(engine, principal) as session:
            original = owned(session, ExportCostQuote, quote_id, principal)
            if original is None:
                raise HTTPException(404, "Quotation not found")
            if body.valid_until < datetime.now(UTC):
                raise HTTPException(422, "Review expiry is in the past")
            if body.prediction_id:
                prediction = session.get(Prediction, body.prediction_id)
                if prediction is None:
                    raise HTTPException(404, "Prediction not found")
                if (
                    prediction.product_id != original.product_id
                    or prediction.destination != original.destination
                    or prediction.synthetic != original.synthetic
                ):
                    raise HTTPException(422, "Prediction does not match quotation")
            payload = {
                "quote": original.payload["quote"],
                "review_status": "VERIFIED_BY_ANALYST",
                "original_quote_id": original.payload.get("original_quote_id", original.record_id),
                "review": {
                    **body.model_dump(mode="json"),
                    "reviewer_id": principal.actor_id,
                    "reviewed_at": datetime.now(UTC).isoformat(),
                },
            }
            return view(
                append_record(
                    session,
                    ExportCostQuote,
                    principal,
                    payload,
                    "quote.review",
                    original.synthetic,
                    product_id=original.product_id,
                    destination=original.destination,
                )
            )

    @router.post("/documents/fetch", status_code=201)
    def fetch_document(
        body: DocumentRequest, principal: Annotated[Principal, Depends(reviewer)]
    ) -> dict:
        try:
            if document_fetcher is not None:
                data = document_fetcher.fetch(body.source_url, use_cache=not body.force_refresh)
            else:
                with httpx.Client(timeout=30) as client:
                    data = DocumentFetcher(
                        client, Path(os.getenv("RAW_STORAGE_PATH", "data/raw"))
                    ).fetch(body.source_url, use_cache=not body.force_refresh)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
        except (httpx.HTTPError, RuntimeError, TransientDocumentError) as error:
            raise HTTPException(
                502, "Official source unavailable; evidence remains unverified"
            ) from error
        text = data.pop("text")
        with tenant_session(engine, principal) as session:
            record = append_record(
                session,
                EvidenceDocument,
                principal,
                data,
                "document.fetch",
                data["synthetic"],
                source_url=data["source_url"],
                content_sha256=data["text_sha256"],
                text_content=text,
            )
            return view(record)

    @router.post("/policies/review", status_code=201)
    def review_policy(
        body: PolicyReview, principal: Annotated[Principal, Depends(reviewer)]
    ) -> dict:
        with tenant_session(engine, principal) as session:
            document = owned(session, EvidenceDocument, body.document_id, principal)
            if document is None:
                raise HTTPException(404, "Evidence document not found")
            product = session.get(Product, body.product_id)
            if product is None or product.hs_code != body.hs_code:
                raise HTTPException(422, "Exact source-supported ITC product mapping required")
            now = datetime.now(UTC)
            if (
                body.evidence_excerpt not in document.text_content
                or body.review_valid_until < now
                or now - datetime.fromisoformat(document.payload["retrieved_at"])
                > timedelta(hours=24)
            ):
                raise HTTPException(422, "Citation, review validity or source freshness unverified")
            host = urlsplit(document.source_url).hostname
            if body.category == GateCategory.DGFT and (
                host not in {"dgft.gov.in", "www.dgft.gov.in", "content.dgft.gov.in"}
                or body.hs_code not in body.evidence_excerpt
            ):
                raise HTTPException(
                    422, "DGFT review requires exact ITC code in DGFT source citation"
                )
            if body.category in {GateCategory.DESTINATION_IMPORT, GateCategory.SPS_CERTIFICATION}:
                authorities = {"682": {"www.sfda.gov.sa"}, "840": {"www.aphis.usda.gov"}}
                if host not in authorities.get(body.country_code, set()):
                    raise HTTPException(422, "Destination authority mapping/source is unverified")
            if body.category == GateCategory.SANCTIONS and host not in {
                "main.un.org",
                "www.un.org",
            }:
                raise HTTPException(
                    422, "Sanctions evidence requires configured authoritative source"
                )
            if body.quote_id:
                scoped_quote = owned(session, ExportCostQuote, body.quote_id, principal)
                if scoped_quote is None:
                    raise HTTPException(404, "Scoped quotation not found")
                if (
                    scoped_quote.product_id != body.product_id
                    or scoped_quote.destination != body.country_code
                    or scoped_quote.synthetic != document.synthetic
                ):
                    raise HTTPException(
                        422, "Shipment review scope differs from document/product/country"
                    )
                if body.category == GateCategory.SANCTIONS:
                    quoted = ShipmentQuote.model_validate(scoped_quote.payload["quote"])
                    if not all(
                        ref in body.review_notes
                        for ref in (quoted.buyer_reference, quoted.logistics_reference)
                    ):
                        raise HTTPException(
                            422,
                            "Sanctions review must identify screened buyer and logistics references; attest all applicable regimes",
                        )
            payload = {
                **body.model_dump(mode="json"),
                "source_url": document.source_url,
                "source_sha256": document.content_sha256,
                "reviewer_id": principal.actor_id,
                "published_at": document.payload["published_at"],
                "document_retrieved_at": document.payload["retrieved_at"],
            }
            return view(
                append_record(
                    session,
                    PolicyRule,
                    principal,
                    payload,
                    "policy.review",
                    document.synthetic,
                    product_id=body.product_id,
                    country_code=body.country_code,
                    document_id=document.record_id,
                    rule_key=body.rule_key,
                )
            )

    @router.get("/documents/{document_id}")
    def document(document_id: str, principal: Annotated[Principal, Depends(reader)]) -> dict:
        """Retrieve the exact archived source text referenced by a private review."""
        with tenant_session(engine, principal) as session:
            record = owned(session, EvidenceDocument, document_id, principal)
            if record is None:
                raise HTTPException(404, "Evidence document not found")
            return {**view(record), "text": record.text_content}

    @router.get("/policies")
    def policies(principal: Annotated[Principal, Depends(reader)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(record) for record in records(session, PolicyRule, principal)]

    @router.get("/risks")
    def risks(principal: Annotated[Principal, Depends(reader)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(record) for record in records(session, CountryRisk, principal)]

    @router.post("/risks/review", status_code=201)
    def review_risk(body: RiskReview, principal: Annotated[Principal, Depends(reviewer)]) -> dict:
        with tenant_session(engine, principal) as session:
            document = owned(session, EvidenceDocument, body.document_id, principal)
            if document is None:
                raise HTTPException(404, "Evidence document not found")
            if (
                body.evidence_excerpt not in document.text_content
                or body.valid_until < datetime.now(UTC)
            ):
                raise HTTPException(422, "Risk citation or validity unverified")
            if session.get(Country, body.country_code) is None:
                raise HTTPException(422, "Unknown country")
            return view(
                append_record(
                    session,
                    CountryRisk,
                    principal,
                    {
                        **body.model_dump(mode="json"),
                        "source_url": document.source_url,
                        "source_sha256": document.content_sha256,
                        "reviewer_id": principal.actor_id,
                        "published_at": document.payload["published_at"],
                        "document_retrieved_at": document.payload["retrieved_at"],
                    },
                    "risk.review",
                    document.synthetic,
                    country_code=body.country_code,
                    document_id=document.record_id,
                )
            )

    @router.post("/events/extract", status_code=201)
    def extract(
        body: ExtractionRequest, principal: Annotated[Principal, Depends(reviewer)]
    ) -> list[dict]:
        with tenant_session(engine, principal) as session:
            document = owned(session, EvidenceDocument, body.document_id, principal)
            if document is None:
                raise HTTPException(404, "Evidence document not found")
            snapshot = {**document.payload, "text": document.text_content}
            products = set(session.scalars(select(Product.product_id)))
            countries = set(session.scalars(select(Country.country_code)))
        try:
            if event_provider is not None:
                events = extract_events(event_provider, snapshot, products, countries, body.query)
            else:
                endpoint = os.getenv("EVENT_EXTRACTOR_ENDPOINT", "")
                if not endpoint:
                    raise HTTPException(
                        503, "Event provider not configured; no LLM events invented"
                    )
                with httpx.Client(timeout=45) as client:
                    provider = HttpEventProvider(
                        endpoint, os.getenv("EVENT_EXTRACTOR_API_KEY", ""), client
                    )
                    events = extract_events(provider, snapshot, products, countries, body.query)
        except (ValueError, ValidationError) as error:
            raise HTTPException(422, "Provider event/citation validation failed") from error
        except httpx.HTTPError as error:
            raise HTTPException(502, "Event provider unavailable") from error
        with tenant_session(engine, principal) as session:
            previous = set(
                session.scalars(
                    select(MarketEvent.event_key).where(
                        MarketEvent.tenant_id == principal.tenant_id
                    )
                )
            )
            document = owned(session, EvidenceDocument, body.document_id, principal)
            if document is None:
                raise HTTPException(404, "Evidence document not found")
            import uuid

            session.add(
                AuditLog(
                    record_id=uuid.uuid4().hex,
                    tenant_id=principal.tenant_id,
                    created_at=datetime.now(UTC),
                    payload={"outcome": "success", "event_count": len(events)},
                    synthetic=document.synthetic,
                    actor_id=principal.actor_id,
                    action="event.extract.request",
                    entity_id=document.record_id,
                )
            )
            output = []
            for event in events:
                payload = event.model_dump(mode="json")
                key = hashlib.sha256(
                    json.dumps(
                        [
                            event.product_id,
                            event.country_code,
                            event.event_type,
                            event.event_date.isoformat(),
                            event.impact_direction,
                        ],
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                if key in previous:
                    continue
                previous.add(key)
                payload.update(
                    published_at=snapshot["published_at"],
                    review_status="UNVERIFIED",
                    source_sha256=document.content_sha256,
                    confidence_kind="text_extraction_confidence_not_forecast_probability",
                )
                output.append(
                    view(
                        append_record(
                            session,
                            MarketEvent,
                            principal,
                            payload,
                            "event.extract",
                            document.synthetic,
                            document_id=document.record_id,
                            event_key=key,
                        )
                    )
                )
            return output

    @router.get("/events")
    def events(principal: Annotated[Principal, Depends(reader)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(record) for record in records(session, MarketEvent, principal)]

    @router.post("/evaluate", status_code=201)
    def evaluate(body: DecisionRequest, principal: Annotated[Principal, Depends(writer)]) -> dict:
        with tenant_session(engine, principal) as session:
            quotation = owned(session, ExportCostQuote, body.quote_id, principal)
            if quotation is None:
                raise HTTPException(404, "Quotation not found")
            prediction = session.get(Prediction, body.prediction_id) if body.prediction_id else None
            if body.prediction_id and prediction is None:
                raise HTTPException(404, "Prediction not found")
            assessment = decide(
                session, principal, quotation, prediction, datetime.now(UTC), body.horizon_days
            )
            record = append_record(
                session,
                CommercialDecision,
                principal,
                assessment,
                "decision.evaluate",
                quotation.synthetic,
                quote_id=quotation.record_id,
                prediction_id=prediction.prediction_id if prediction else None,
            )
            from src.ranking.alerts import emit_alerts

            emit_alerts(session, principal, record)
            return view(record)

    @router.get("/decisions/{decision_id}")
    def decision(decision_id: str, principal: Annotated[Principal, Depends(reader)]) -> dict:
        with tenant_session(engine, principal) as session:
            record = owned(session, CommercialDecision, decision_id, principal)
            if record is None:
                raise HTTPException(404, "Decision not found")
            return view(record)

    @router.get("/decisions")
    def decisions(principal: Annotated[Principal, Depends(reader)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [view(record) for record in records(session, CommercialDecision, principal)]

    @router.get("/audits")
    def audits(principal: Annotated[Principal, Depends(administrator)]) -> list[dict]:
        with tenant_session(engine, principal) as session:
            return [
                {
                    **view(record),
                    "actor_id": record.actor_id,
                    "action": record.action,
                    "entity_id": record.entity_id,
                }
                for record in records(session, AuditLog, principal)
            ]

    return router
