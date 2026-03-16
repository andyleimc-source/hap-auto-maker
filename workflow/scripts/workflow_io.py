"""
Shared HTTP session, output persistence, and run logging for workflow scripts.

Usage in each script:

    from workflow_io import Session, persist

    session = Session(cookie, account_id, authorization, origin)
    data = session.post("https://...", {"key": "value"})
    data = session.get("https://...")

    persist("script_name", output, args=log_args, session=session, started_at=started_at)

Writes:
  output/{script}_{timestamp}.json   — timestamped output snapshot
  output/{script}_latest.json        — always-overwritten, for downstream scripts
  logs/{script}_{timestamp}.json     — run log (args + output + requests + error + duration)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests as _requests


_SCRIPTS_DIR = Path(__file__).parent
_WORKFLOW_DIR = _SCRIPTS_DIR.parent
_OUTPUT_DIR = _WORKFLOW_DIR / "output"
_LOGS_DIR = _WORKFLOW_DIR / "logs"


class Session:
    """
    Thin wrapper around requests.Session.

    - Injects auth headers (Cookie, AccountId, Authorization) once at construction.
    - Records every request's method, URL, HTTP status, duration, and error.
    - Supports per-request header overrides (e.g. Referer) via extra_headers.
    """

    def __init__(
        self,
        cookie: str,
        account_id: str = "",
        authorization: str = "",
        origin: str = "https://www.mingdao.com",
    ) -> None:
        self._s = _requests.Session()
        self._history: list[dict] = []

        self._s.headers.update({
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": origin,
            "Referer": "https://www.mingdao.com/",
            "X-Requested-With": "XMLHttpRequest",
        })
        if cookie:
            self._s.headers["Cookie"] = cookie
        if account_id:
            self._s.headers["AccountId"] = account_id
            self._s.headers["accountid"] = account_id
        if authorization:
            self._s.headers["Authorization"] = authorization

    def post(self, url: str, payload: dict, extra_headers: dict | None = None) -> dict:
        t0 = time.time()
        entry: dict = {"method": "POST", "url": url}
        try:
            resp = self._s.post(url, json=payload, headers=extra_headers, timeout=30)
            entry["status"] = resp.status_code
            entry["duration_ms"] = round((time.time() - t0) * 1000)
            resp.raise_for_status()
            self._history.append(entry)
            return resp.json()
        except _requests.HTTPError as err:
            entry["error"] = f"HTTP {err.response.status_code}: {err.response.text[:300]}"
            entry["duration_ms"] = round((time.time() - t0) * 1000)
            self._history.append(entry)
            raise RuntimeError(entry["error"]) from err
        except _requests.RequestException as err:
            entry["error"] = str(err)
            entry["duration_ms"] = round((time.time() - t0) * 1000)
            self._history.append(entry)
            raise RuntimeError(f"Network error: {err}") from err

    def get(self, url: str) -> dict:
        t0 = time.time()
        entry: dict = {"method": "GET", "url": url}
        try:
            resp = self._s.get(url, timeout=30)
            entry["status"] = resp.status_code
            entry["duration_ms"] = round((time.time() - t0) * 1000)
            resp.raise_for_status()
            self._history.append(entry)
            return resp.json()
        except _requests.HTTPError as err:
            entry["error"] = f"HTTP {err.response.status_code}: {err.response.text[:300]}"
            entry["duration_ms"] = round((time.time() - t0) * 1000)
            self._history.append(entry)
            raise RuntimeError(entry["error"]) from err
        except _requests.RequestException as err:
            entry["error"] = str(err)
            entry["duration_ms"] = round((time.time() - t0) * 1000)
            self._history.append(entry)
            raise RuntimeError(f"Network error: {err}") from err

    @property
    def history(self) -> list[dict]:
        return self._history


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def persist(
    script: str,
    output: dict | None,
    *,
    args: dict | None = None,
    error: str | None = None,
    started_at: float | None = None,
    session: Session | None = None,
) -> None:
    """Save output and log files. Call once per script run."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    duration_ms = round((time.time() - started_at) * 1000) if started_at else None

    # ── output files (only when there's data) ────────────────────────────────
    if output is not None:
        _write(_OUTPUT_DIR / f"{script}_latest.json", output)
        print(f"[output] output/{script}_latest.json", file=sys.stderr)

    # ── log file ──────────────────────────────────────────────────────────────
    log: dict = {
        "script": script,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "duration_ms": duration_ms,
        "args": args or {},
        "requests": session.history if session else [],
        "output": output,
        "error": error,
    }
    _write(_LOGS_DIR / f"{script}_{ts}.json", log)
    print(f"[log]    logs/{script}_{ts}.json", file=sys.stderr)
