"""Import-time isolation for the sync code (sync spec §6.1, §8).

The acceptance suite asserts that a deck with sync off opens no sockets. That
promise is easy to break by adding one module-level import, and a socket count
alone would not catch it: ``http.client`` and ``ssl`` import cleanly without
opening anything. So the test also asserts that the network modules are not
even loaded.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PROBE = """
import socket, sys

opened = []
real = socket.socket


class Spy(real):
    def __init__(self, *args, **kwargs):
        opened.append(args)
        super().__init__(*args, **kwargs)


socket.socket = Spy
import lurkn.app  # noqa: F401

network = [name for name in ("lurkn.syncclient", "lurkn.syncer", "lurkn.syncui")
           if name in sys.modules]
print(len(opened), ",".join(network))
"""


def test_importing_the_app_opens_no_sockets_and_loads_no_network_modules() -> None:
    completed = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )

    # The probe prints "0" plus a comma-joined module list, which is empty.
    first = completed.stdout.strip().splitlines()[0]
    count, _, modules = first.partition(" ")
    assert count == "0", "importing the app must not open a socket"
    assert modules == "", f"network modules imported before opt-in: {modules}"


def test_the_sync_store_modules_are_importable_without_gi_or_network() -> None:
    # syncer and syncsettings are pure; only syncui reaches for GLib.
    completed = subprocess.run(
        [sys.executable, "-c", "import lurkn.syncer, lurkn.syncsettings, lurkn.queue; print('ok')"],
        cwd=ROOT,
        env={"PYTHONPATH": str(ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "ok"
