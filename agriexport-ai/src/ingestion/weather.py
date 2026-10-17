"""NASA POWER daily observations; acquisition time is availability, never historic hindsight."""

import argparse
import hashlib
import json
import math
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
from tenacity import Retrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.ingestion.storage import archive

NASA_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"


class WeatherSourceError(Exception):
    """Transient upstream error, not a valid meteorological measurement."""


class NasaPowerConnector:
    """One grid-point query with cache, retries, exact bytes and validated units."""

    def __init__(self, client: httpx.Client, raw_root: Path, synthetic: bool = False):
        self.client, self.raw_root, self.synthetic = client, raw_root, synthetic

    def fetch(self, latitude: float, longitude: float, start: date, end: date) -> dict:
        """Return validated temperature/rainfall context. Do not infer agricultural exposure."""
        if not (-90 <= latitude <= 90 and -180 <= longitude <= 180) or start > end:
            raise ValueError("Valid coordinates and date range required")
        if end >= datetime.now(UTC).date():
            raise ValueError("NASA daily observations require completed historical dates")
        if (end - start).days > 366:
            raise ValueError("Limit one query to at most 367 days; respect grid/source limits")
        parameters = {
            "parameters": "T2M,PRECTOTCORR",
            "community": "AG",
            "latitude": latitude,
            "longitude": longitude,
            "start": start.strftime("%Y%m%d"),
            "end": end.strftime("%Y%m%d"),
            "format": "JSON",
            "time-standard": "UTC",
        }
        url = str(httpx.URL(NASA_URL, params=parameters))
        key = hashlib.sha256((url + str(self.synthetic)).encode()).hexdigest()
        cache = self.raw_root / "cache" / f"nasa-{key}.json"
        if cache.exists():
            entry = json.loads(cache.read_text())
            observed = datetime.fromisoformat(entry["retrieved_at"])
            if datetime.now(UTC) - observed < timedelta(hours=24):
                raw = self.raw_root / (entry["sha256"] + ".raw")
                payload = raw.read_bytes()
                if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                    raise ValueError("NASA raw/cache integrity failure")
                return self.normalize(payload, raw, observed, url, start, end)
        for attempt in Retrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential(min=2, max=8),
            retry=retry_if_exception_type((httpx.TransportError, WeatherSourceError)),
            reraise=True,
        ):
            with attempt:
                response = self.client.get(NASA_URL, params=parameters)
                observed = datetime.now(UTC)
                _, raw = archive(self.raw_root, response.content, url, observed, self.synthetic)
                if response.status_code == 429:
                    raise RuntimeError(
                        "NASA rate limited; Retry-After="
                        + response.headers.get("Retry-After", "unverified")
                    )
                if response.status_code >= 500:
                    raise WeatherSourceError(f"NASA HTTP {response.status_code}")
                response.raise_for_status()
        output = self.normalize(response.content, raw, observed, url, start, end)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"sha256": raw.stem, "retrieved_at": observed.isoformat()}))
        return output

    def normalize(
        self, payload: bytes, raw: Path, observed: datetime, source_url: str, start: date, end: date
    ) -> dict:
        """Fail the batch on fill values, missing days or changed units; never fill rain with zero."""
        body = json.loads(payload)
        header = body.get("header", {})
        if header.get("time_standard") != "UTC":
            raise ValueError("NASA time standard unverified")
        values = body.get("properties", {}).get("parameter", {})
        metadata = body.get("parameters", {})
        expected_days = {
            (start + timedelta(days=i)).strftime("%Y%m%d") for i in range((end - start).days + 1)
        }
        rows = []
        for variable, unit in (("T2M", "C"), ("PRECTOTCORR", "mm/day")):
            if (
                metadata.get(variable, {}).get("units") != unit
                or set(values.get(variable, {})) != expected_days
            ):
                raise ValueError("NASA parameter units/date coverage unverified")
            for day, value in sorted(values[variable].items()):
                if (
                    not isinstance(value, (int, float))
                    or not math.isfinite(value)
                    or value == header.get("fill_value", -999)
                    or variable == "PRECTOTCORR"
                    and value < 0
                ):
                    raise ValueError("NASA missing/invalid measurement; not calculated")
                rows.append(
                    {
                        "variable": variable,
                        "value": value,
                        "unit": unit,
                        "event_date": datetime.strptime(day, "%Y%m%d").date().isoformat(),
                    }
                )
        return {
            "source_url": source_url,
            "raw_sha256": raw.stem,
            "retrieved_at": observed.isoformat(),
            "published_at": observed.isoformat(),
            "availability_basis": "first_observed",
            "forecast_run_at": None,
            "time_standard": "UTC",
            "measurements": rows,
            "synthetic": self.synthetic,
            "label": "SYNTHETIC" if self.synthetic else "SOURCE_OBSERVATIONS",
            "crop_region_mapping": "unverified",
            "model_feature_use": "not_enabled",
        }


def main() -> None:
    """Write audited point-weather context, without claiming a crop yield or a nowcast model."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with httpx.Client(timeout=60) as client:
        report = NasaPowerConnector(client, Path(os.getenv("RAW_STORAGE_PATH", "data/raw"))).fetch(
            args.latitude, args.longitude, args.start, args.end
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "source": "NASA_POWER",
                "rows": len(report["measurements"]),
                "output": str(args.output),
                "availability_basis": "first_observed",
                "crop_region_mapping": "unverified",
            }
        )
    )


if __name__ == "__main__":
    main()
