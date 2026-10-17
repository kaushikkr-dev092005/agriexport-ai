"""Run the local built landing/dashboard and API together; stop both on Ctrl+C."""

import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx

from src.database.repository import init_local, make_engine

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    """Use an installed Node or the verified portable copy; do not install a service."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--smoke", action="store_true", help="Check both HTTP servers and stop")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--dashboard-port", type=int, default=3000)
    args = parser.parse_args()
    dashboard = ROOT / "apps/dashboard"
    node = shutil.which("node") or str(ROOT / "data/tools/node/node.exe")
    if not Path(node).is_file() or not (dashboard / "node_modules/next/dist/bin/next").is_file():
        raise SystemExit("Node/dependencies missing. See PHASE4.md for setup_node and npm ci.")
    if not (dashboard / ".next/BUILD_ID").is_file():
        raise SystemExit("Build the dashboard first: npm run build in apps/dashboard.")
    if args.api_port == args.dashboard_port:
        raise SystemExit("API and dashboard need different ports")
    for port in (args.api_port, args.dashboard_port):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", port))
    engine = make_engine(
        os.getenv("DATABASE_URL", f"sqlite:///{(ROOT / 'data/local.db').as_posix()}")
    )
    try:
        if engine.dialect.name == "sqlite":
            init_local(engine)
    finally:
        engine.dispose()
    logs = ROOT / "data" / ("preview-" + uuid.uuid4().hex[:12])
    logs.mkdir(parents=True, exist_ok=True)
    api_url, dashboard_url = (
        f"http://127.0.0.1:{args.api_port}",
        f"http://127.0.0.1:{args.dashboard_port}",
    )
    environment = dict(
        os.environ,
        AGRI_API_ORIGIN=api_url,
        AGRI_DASHBOARD_ORIGIN=dashboard_url,
        NEXT_TELEMETRY_DISABLED="1",
    )
    processes = []
    handles = []
    try:
        for command, cwd, label in (
            (
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "apps.api.main:create_app",
                    "--factory",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(args.api_port),
                ],
                ROOT,
                "api",
            ),
            (
                [
                    node,
                    "node_modules/next/dist/bin/next",
                    "start",
                    "--hostname",
                    "127.0.0.1",
                    "--port",
                    str(args.dashboard_port),
                ],
                dashboard,
                "dashboard",
            ),
        ):
            handle = (logs / f"{label}.log").open("wb")
            handles.append(handle)
            child_environment = dict(environment)
            if label == "dashboard":
                for key in (
                    "AGRI_AUTH_CREDENTIALS",
                    "DATABASE_URL",
                    "EVENT_EXTRACTOR_API_KEY",
                    "COMTRADE_API_KEY",
                ):
                    child_environment.pop(key, None)
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=cwd,
                    env=child_environment,
                    stdout=handle,
                    stderr=handle,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            )
        with httpx.Client(timeout=2) as client:
            for url in (
                api_url + "/api/v1/health",
                dashboard_url + "/",
                dashboard_url + "/dashboard",
            ):
                ready = False
                for _ in range(100):
                    if any(p.poll() is not None for p in processes):
                        raise RuntimeError(f"Preview exited; see {logs}")
                    try:
                        ready = client.get(url).is_success
                    except httpx.HTTPError:
                        ready = False
                    if ready:
                        break
                    time.sleep(0.2)
                if not ready:
                    raise RuntimeError(f"Preview not healthy; run migrations and inspect {logs}")
        print(
            f"Landing: {dashboard_url}/\nWorkspace: {dashboard_url}/dashboard\nAPI docs: {api_url}/docs\nLogs: {logs}",
            flush=True,
        )
        if args.smoke:
            print(
                "Local API + landing + dashboard HTTP smoke passed; stopping owned servers.",
                flush=True,
            )
            return
        print("Press Ctrl+C to stop both servers.", flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
        for handle in handles:
            handle.close()


if __name__ == "__main__":
    main()
