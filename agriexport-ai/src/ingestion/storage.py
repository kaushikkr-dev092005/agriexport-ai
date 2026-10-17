"""Local content-addressed raw storage; an object-store adapter is future work."""

import hashlib
import json
from datetime import datetime
from pathlib import Path


def archive(
    root: Path, payload: bytes, source_url: str, retrieved_at: datetime, synthetic: bool = False
) -> tuple[str, Path]:
    """Preserve exact raw bytes and append a retrieval manifest without secrets."""
    digest = hashlib.sha256(payload).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{digest}.raw"
    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
        raise ValueError("Raw archive integrity failure")
    if not target.exists():
        target.write_bytes(payload)
    with (root / "retrievals.jsonl").open("a", encoding="utf-8") as output:
        output.write(
            json.dumps(
                {
                    "sha256": digest,
                    "source_url": source_url,
                    "retrieved_at": retrieved_at.isoformat(),
                    "synthetic": synthetic,
                }
            )
            + "\n"
        )
    return digest, target
