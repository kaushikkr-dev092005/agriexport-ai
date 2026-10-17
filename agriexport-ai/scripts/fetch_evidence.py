"""Retrieve one public official text snapshot, without making legal interpretations."""

import argparse
import json
import os
from pathlib import Path

import httpx

from src.intelligence.evidence import DocumentFetcher, TransientDocumentError


def main() -> None:
    """Archive raw content and print metadata only; an index page is not legal clearance."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    try:
        with httpx.Client(timeout=30) as client:
            result = DocumentFetcher(client, Path(os.getenv("RAW_STORAGE_PATH", "data/raw"))).fetch(
                args.url, use_cache=not args.refresh
            )
    except (httpx.HTTPError, ValueError, RuntimeError, TransientDocumentError) as error:
        print(json.dumps({"interpretation_status": "UNVERIFIED", "error": str(error)}))
        raise SystemExit(1) from None
    text = result.pop("text")
    result["text_characters"] = len(text)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
