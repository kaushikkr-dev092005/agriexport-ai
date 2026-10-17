"""Public country and commodity context, with no imputed shortages or commercial rules."""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.database.models import Country, Product
from src.database.repository import snapshot
from src.forecasting.service import latest_forecasts


def create_intelligence_router(engine: Engine) -> APIRouter:
    """Historical context endpoints deliberately leave unavailable market statistics null."""
    router = APIRouter(prefix="/api/v1", tags=["Public intelligence"])

    @router.get("/countries")
    def countries() -> list[dict]:
        with Session(engine) as session:
            return [
                {"country_code": c.country_code, "name": c.name}
                for c in session.scalars(select(Country).order_by(Country.name))
            ]

    @router.get("/markets/{country_code}")
    def market(country_code: str) -> dict:
        with Session(engine) as session:
            country = session.get(Country, country_code)
            if country is None:
                raise HTTPException(404, "Country reference unverified")
            now = datetime.now(UTC)
            rows = [
                r
                for r in snapshot(session, now, limit=1000)
                if (r.flow == "X" and r.partner == country_code)
                or (r.flow == "M" and r.reporter == country_code)
            ]
            return {
                "country_code": country.country_code,
                "name": country.name,
                "as_of": now.isoformat(),
                "import_dependence": None,
                "production_outlook": None,
                "current_suppliers": None,
                "restrictions": "UNVERIFIED",
                "status": "HISTORICAL_CONTEXT_ONLY",
                "forecast_contexts": latest_forecasts(session, now, destination=country_code),
                "historical_observations": len(rows),
                "coverage_note": "Stored sample only; not complete destination demand or supplier coverage",
                "sources": sorted({r.source_url for r in rows}),
            }

    @router.get("/commodities/{product_id}")
    def commodity(product_id: str) -> dict:
        with Session(engine) as session:
            product = session.get(Product, product_id)
            if product is None:
                raise HTTPException(404, "Product reference unverified")
            now = datetime.now(UTC)
            rows = snapshot(session, now, product_id=product_id, limit=1000)
            return {
                "product": product.metadata_json,
                "as_of": now.isoformat(),
                "indian_supply_tonnes": None,
                "current_price": None,
                "competitor_prices": None,
                "status": "HISTORICAL_CONTEXT_ONLY",
                "historical_observations": len(rows),
                "forecast_contexts": latest_forecasts(session, now, product_id=product_id),
                "sources": sorted({r.source_url for r in rows}),
            }

    return router
