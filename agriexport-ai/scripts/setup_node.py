"""Install a checksum-verified official portable Node LTS beneath ignored data/tools."""

import hashlib
import io
import json
import zipfile
from pathlib import Path

import httpx


def main() -> None:
    """No system installation, PATH edits, services or executable shell downloads."""
    root = Path("data/tools/node").resolve()
    with httpx.Client(timeout=120, follow_redirects=True) as client:
        index = client.get("https://nodejs.org/dist/index.json")
        index.raise_for_status()
        version = next(
            r["version"] for r in index.json() if r["version"].startswith("v22.") and r["lts"]
        )
        name = f"node-{version}-win-x64.zip"
        base = f"https://nodejs.org/dist/{version}/"
        checksums = client.get(base + "SHASUMS256.txt")
        checksums.raise_for_status()
        expected = next(
            line.split()[0] for line in checksums.text.splitlines() if line.split()[-1] == name
        )
        response = client.get(base + name)
        response.raise_for_status()
    if hashlib.sha256(response.content).hexdigest() != expected:
        raise ValueError("Official Node archive checksum mismatch")
    root.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for item in archive.infolist():
            relative = Path(*Path(item.filename).parts[1:])
            target = (root / relative).resolve()
            if not target.is_relative_to(root):
                raise ValueError("Archive escapes tool directory")
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
    print(
        json.dumps(
            {
                "node": str(root / "node.exe"),
                "version": version,
                "sha256": expected,
                "source": base + name,
            }
        )
    )


if __name__ == "__main__":
    main()
