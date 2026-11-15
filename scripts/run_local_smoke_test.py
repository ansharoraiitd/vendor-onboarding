#!/usr/bin/env python3
"""
scripts/run_local_smoke_test.py — Spin up local uvicorn on fresh empty DATA_DIR,
execute smoke_live.py over HTTP, and terminate cleanly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def main():
    fresh_dir = tempfile.mkdtemp(prefix="fresh_smoke_data_")
    print(f"Created fresh DATA_DIR: {fresh_dir}")

    env = os.environ.copy()
    env["DATA_DIR"] = fresh_dir
    env["DB_PATH"] = os.path.join(fresh_dir, "vendor_onboarding.db")
    env["EXTRACTION_CACHE_DIR"] = os.path.join(fresh_dir, "extraction_cache")
    env["DEMO_MODE"] = "true"
    env["PORT"] = "8088"

    # Pre-copy disk cache into EXTRACTION_CACHE_DIR to mirror container /app/seed_cache behavior
    os.makedirs(env["EXTRACTION_CACHE_DIR"], exist_ok=True)
    seed_cache_src = project_root / "data" / "extraction_cache"
    if seed_cache_src.exists():
        for f in seed_cache_src.glob("*.json"):
            shutil.copy2(f, Path(env["EXTRACTION_CACHE_DIR"]) / f.name)

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            "8088",
            "--log-level",
            "warning",
        ],
        cwd=str(project_root),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    base_url = "http://127.0.0.1:8088"

    try:
        # Wait for server to be responsive
        server_ready = False
        for _ in range(30):
            time.sleep(0.5)
            try:
                r = httpx.get(f"{base_url}/health", timeout=2.0)
                if r.status_code == 200:
                    server_ready = True
                    break
            except Exception:
                pass

        if not server_ready:
            print("❌ Failed to connect to local uvicorn server within 15 seconds.")
            stderr_out = proc.stderr.read().decode() if proc.stderr else ""
            stdout_out = proc.stdout.read().decode() if proc.stdout else ""
            print("Uvicorn stderr:", stderr_out)
            print("Uvicorn stdout:", stdout_out)
            return 1

        # Run smoke test over HTTP
        from scripts.smoke_live import run_smoke_test
        success = run_smoke_test(base_url)
        return 0 if success else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(fresh_dir, ignore_errors=True)
        print("Cleaned up temporary DATA_DIR.")


if __name__ == "__main__":
    sys.exit(main())
