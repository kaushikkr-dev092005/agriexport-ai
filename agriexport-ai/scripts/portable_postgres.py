"""Download official vendor binaries and run an isolated, temporary PostgreSQL test."""

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path

import httpx
from bs4 import BeautifulSoup


def run(arguments: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run console binaries without creating visible Windows windows."""
    # pg_ctl descendants may inherit pipes after pg_ctl exits on Windows. Files avoid
    # waiting for server-held pipe EOF while retaining diagnostics for failed checks.
    with tempfile.TemporaryFile(mode="w+b") as output, tempfile.TemporaryFile(mode="w+b") as errors:
        process = subprocess.run(
            arguments,
            check=False,
            stdout=output,
            stderr=errors,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            **kwargs,
        )
        output.seek(0)
        errors.seek(0)
        result = subprocess.CompletedProcess(
            arguments,
            process.returncode,
            output.read().decode("utf-8", errors="replace"),
            errors.read().decode("utf-8", errors="replace"),
        )
    if result.returncode:
        raise subprocess.CalledProcessError(
            result.returncode, arguments, output=result.stdout, stderr=result.stderr
        )
    return result


def main() -> None:
    """Install only beneath ignored data/tools; no service registration or deletion."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true")
    args = parser.parse_args()
    root = Path("data/tools").resolve()
    root.mkdir(parents=True, exist_ok=True)
    executable = root / "pgsql/bin/pg_ctl.exe"
    archive_path = root / "postgres16.zip"
    if not executable.exists():
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            response = client.get("https://www.enterprisedb.com/download-postgresql-binaries")
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            url = None
            for image in soup.find_all("img", alt="Windows x86-64"):
                parent = image.parent
                while parent and "Version" not in parent.get_text():
                    parent = parent.parent
                if parent and "Version 16." in parent.get_text():
                    url = image.parent["href"]
                    break
            if not url or not url.startswith("https://sbp.enterprisedb.com/"):
                raise ValueError("Official PostgreSQL 16 download link not verified")
            if not archive_path.exists():
                partial = archive_path.with_suffix(".partial")
                with client.stream("GET", url) as stream, partial.open("wb") as output:
                    stream.raise_for_status()
                    for chunk in stream.iter_bytes():
                        output.write(chunk)
                partial.replace(archive_path)
            checksum = hashlib.file_digest(archive_path.open("rb"), "sha256").hexdigest()
            (root / "download.json").write_text(
                json.dumps(
                    {
                        "source_url": url,
                        "sha256": checksum,
                        "scope": "local PostgreSQL acceptance only",
                    }
                )
            )
        with zipfile.ZipFile(archive_path) as compressed:
            for entry in compressed.infolist():
                if not entry.filename.startswith(("pgsql/bin/", "pgsql/lib/", "pgsql/share/")):
                    continue
                target = (root / entry.filename).resolve()
                if not target.is_relative_to(root):
                    raise ValueError("Archive path escapes intended tool directory")
                compressed.extract(entry, root)
    print(json.dumps({"postgres_binary": str(executable), "status": "downloaded"}), flush=True)
    if not args.test:
        return
    cluster = Path("data") / ("pg-acceptance-" + uuid.uuid4().hex)
    cluster = cluster.resolve()
    binary = executable.parent
    # Trust auth is confined to this disposable loopback-only synthetic/public-data test.
    run(
        [
            str(binary / "initdb.exe"),
            "-D",
            str(cluster),
            "-U",
            "agriexport_test",
            "--auth=trust",
            "--encoding=UTF8",
            "--no-locale",
        ]
    )
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    run(
        [
            str(executable),
            "-D",
            str(cluster),
            "-l",
            str(cluster / "server.log"),
            "-o",
            f"-h 127.0.0.1 -p {port} -F",
            "-w",
            "start",
        ]
    )
    environment = dict(os.environ)
    environment["AGRI_ALLOW_TEST_ROLE_CREATION"] = "1"
    environment["POSTGRES_TEST_URL"] = (
        f"postgresql+psycopg://agriexport_test@127.0.0.1:{port}/agriexport_acceptance"
    )
    environment["DATABASE_URL"] = environment["POSTGRES_TEST_URL"]
    try:
        run(
            [
                str(binary / "createdb.exe"),
                "-h",
                "127.0.0.1",
                "-p",
                str(port),
                "-U",
                "agriexport_test",
                "agriexport_acceptance",
            ]
        )
        for command in (
            [sys.executable, "-m", "pytest", "-q"],
            [
                sys.executable,
                "-m",
                "src.cli",
                "import-commerce",
                "--product",
                "basmati_rice",
                "--hs",
                "10063020",
                "--period",
                "202501",
                "--partner",
                "682",
            ],
            [
                sys.executable,
                "-m",
                "src.cli",
                "comtrade",
                "--product",
                "rice",
                "--hs",
                "1006",
                "--reporter",
                "156",
                "--partner",
                "000",
                "--flow",
                "M",
                "--period",
                "202401",
            ],
            [sys.executable, "-m", "src.forecasting.cli", "forecast"],
            [sys.executable, "-m", "scripts.smoke_api"],
        ):
            result = run(command, env=environment)
            print(result.stdout, flush=True)
        print(
            json.dumps(
                {
                    "postgres_acceptance": "passed",
                    "cluster": str(cluster),
                    "service_installed": False,
                }
            ),
            flush=True,
        )
    except subprocess.CalledProcessError as error:
        print(error.stdout)
        print(error.stderr)
        raise
    finally:
        run([str(executable), "-D", str(cluster), "-m", "fast", "-w", "stop"])


if __name__ == "__main__":
    main()
