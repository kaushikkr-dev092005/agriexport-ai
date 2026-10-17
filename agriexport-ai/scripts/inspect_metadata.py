"""Inspect locally archived source metadata without printing session tokens."""

import json
from pathlib import Path

from bs4 import BeautifulSoup


def main() -> None:
    """Print bounded report-unit and vendor-version context."""
    soup = BeautifulSoup(
        Path("data/probes/commerce-2.html").read_text(encoding="utf-8"), "html.parser"
    )
    label = soup.find(string=lambda text: text and "Commodity:" in text)
    print(json.dumps({"commodity_header": str(label.parent.parent)[:1500]}))
    soup = BeautifulSoup(Path("data/probes/edb.html").read_text(encoding="utf-8"), "html.parser")
    for image in soup.find_all("img", alt="Windows x86-64")[:4]:
        parent = image.parent
        while parent and "Version" not in parent.get_text():
            parent = parent.parent
        print(
            json.dumps(
                {
                    "url": image.parent.get("href"),
                    "version": parent.get_text(" ", strip=True)[:80] if parent else None,
                }
            )
        )


if __name__ == "__main__":
    main()
