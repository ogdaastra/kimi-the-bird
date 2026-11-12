"""Command-line entry point.

    python main.py              # desktop app (shows setup on first launch)
    python main.py --headless   # run Kimi without a window (e.g. at login)
    python main.py --demo       # visitor-note demonstration (offline mock, no credits)
    python main.py --demo --live  # same demonstration using your real API key
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading
import time
from pathlib import Path

from . import APP_NAME, MODEL_ID, __version__, credentials
from .config import Paths, default_data_root
from .instance_lock import InstanceLock
from .logging_setup import configure_logging

MOCK_KEY = "offline-mock-key-not-a-real-key"


def _parse(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="kimi", description=f"{APP_NAME} - an autonomous digital bird ({MODEL_ID}).")
    p.add_argument("--headless", action="store_true", help="run without a window")
    p.add_argument("--demo", action="store_true", help="run the visitor-note demonstration")
    p.add_argument("--live", action="store_true", help="with --demo: use the real API key (costs a fraction of a cent)")
    p.add_argument("--mock-ai", action="store_true",
                   help="use an offline stand-in for Haiku (no API calls, no key needed) - for trying things out")
    p.add_argument("--data-dir", type=Path, default=None, help="where Kimi's world is stored (default: ./data)")
    p.add_argument("--verbose", action="store_true", help="log to the console")
    p.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    return p.parse_args(argv)


def run_headless(paths: Paths, mock: bool) -> int:
    from .ai.mock import mock_factory
    from .runtime import KimiRuntime

    if not mock:
        ok, description = credentials.secure_storage_status()
        if not ok:
            print(f"Secure credential storage unavailable: {description}")
            return 2
        if not credentials.has_api_key():
            print("No API key configured. Start Kimi once without --headless to enter your key.")
            return 2
    rt = KimiRuntime(
        paths,
        sdk_factory=mock_factory() if mock else None,
        key_provider=(lambda: MOCK_KEY) if mock else None,
    )
    stop = threading.Event()

    def _handle(*_):
        stop.set()

    signal.signal(signal.SIGINT, _handle)
    signal.signal(signal.SIGTERM, _handle)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _handle)  # type: ignore[attr-defined]
    rt.start()
    print(f"{APP_NAME} is running headless. Press Ctrl+C to stop. Data: {paths.root}")
    running, url, problem = rt.web_status()
    if running:
        print(f"Web page: {url} (this PC only; see docs/REMOTE_ACCESS.md to view it from your phone)")
    elif problem:
        print(f"Web page not running: {problem}")
    try:
        while not stop.wait(60):
            s = rt.snapshot()
            print(f"[{time.strftime('%H:%M')}] Day {s['day']} {s['clock']} | {s['status_text']} | "
                  f"{s['place_name']} | {s['activity']} | spent today ${s['spent_today']:.4f}")
    finally:
        rt.shutdown()
        print("Kimi's world has been saved. Goodbye!")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    paths = Paths(args.data_dir.expanduser().resolve() if args.data_dir else default_data_root())
    if args.demo:
        from .demo import run_demo

        configure_logging(None, console=args.verbose)
        return run_demo(live=args.live, data_dir=args.data_dir)
    paths.ensure()
    configure_logging(paths.logs, console=args.verbose or args.headless)
    lock = InstanceLock(paths.lock_file)
    if not lock.acquire():
        message = "Kimi is already running (only one copy can use the same world at a time)."
        if args.headless:
            print(message)
        else:
            try:
                from PySide6.QtWidgets import QApplication, QMessageBox

                app = QApplication.instance() or QApplication(sys.argv)
                QMessageBox.information(None, APP_NAME, message)
            except Exception:  # noqa: BLE001
                print(message)
        return 1
    try:
        if args.headless:
            return run_headless(paths, args.mock_ai)
        from .ui.app import run_gui

        return run_gui(paths, mock=args.mock_ai)
    finally:
        lock.release()
