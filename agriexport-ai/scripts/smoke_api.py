"""Launch an actual local HTTP server, verify Phase 1 endpoints, then stop it."""

import json
import os
import socket
import subprocess
import sys
import time

import httpx


def main() -> None:
    """Requires an initialized DATABASE_URL or default local database."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "apps.api.main:create_app",
            "--factory",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=2) as client:
            for attempt in range(50):
                try:
                    response = client.get("/api/v1/health")
                    response.raise_for_status()
                    break
                except httpx.HTTPError:
                    if process.poll() is not None or attempt == 49:
                        raise RuntimeError("HTTP smoke server did not become healthy") from None
                    time.sleep(0.1)
            health = response.json()
            products = client.get("/api/v1/products")
            products.raise_for_status()
            trade = client.get("/api/v1/trade")
            trade.raise_for_status()
            opportunities = client.get("/api/v1/opportunities")
            opportunities.raise_for_status()
            forecasts = client.get("/api/v1/forecasts")
            forecasts.raise_for_status()
            assert all(
                p["horizon_days"] in {7, 14, 28} and p["quantity_tonnes"] is None
                for p in forecasts.json()
            )
            assert all(p["score"] is None for p in opportunities.json()["blocked_items"])
            if forecasts.json():
                detail = client.get("/api/v1/opportunities/" + forecasts.json()[0]["prediction_id"])
                detail.raise_for_status()
                assert detail.json()["evidence"]
            assert health["phase"] == 4 and not health["live_opportunities"]
            assert len(products.json()) >= 18
            assert opportunities.json()["score"] is None
            docs = client.get("/docs")
            docs.raise_for_status()
            assert client.get("/api/v1/commercial/quotes").status_code == 401
            assert client.post("/api/v1/commercial/evaluate", json={}).status_code == 401
            print(
                json.dumps(
                    {
                        "http_smoke": "passed",
                        "products": len(products.json()),
                        "trade_rows": len(trade.json()),
                        "models": health["models"],
                        "forecast_contexts": len(forecasts.json()),
                        "blocked_candidates": len(opportunities.json()["blocked_items"]),
                    }
                )
            )
    finally:
        process.terminate()
        process.wait(timeout=5)


if __name__ == "__main__":
    main()
