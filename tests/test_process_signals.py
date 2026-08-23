from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
from pathlib import Path

from pyqt_reactive.process_signals import QtProcessSignalRelay


def test_signal_relay_restores_process_handlers(qapp) -> None:
    previous_handlers = {
        signal_number: signal.getsignal(signal_number)
        for signal_number in (signal.SIGINT, signal.SIGTERM)
    }

    relay = QtProcessSignalRelay(qapp)
    relay.close()

    assert {
        signal_number: signal.getsignal(signal_number) for signal_number in previous_handlers
    } == previous_handlers


def test_signal_relay_does_not_restore_over_a_newer_handler(qapp) -> None:
    previous_handler = signal.getsignal(signal.SIGINT)

    def replacement_handler(_signal_number, _frame) -> None:
        pass

    relay = QtProcessSignalRelay(qapp, handled_signals=(signal.SIGINT,))
    signal.signal(signal.SIGINT, replacement_handler)
    try:
        relay.close()
        assert signal.getsignal(signal.SIGINT) is replacement_handler
    finally:
        signal.signal(signal.SIGINT, previous_handler)


def test_signal_relay_exits_qt_loop_without_keyboard_interrupt_traceback() -> None:
    source_root = Path(__file__).resolve().parents[1] / "src"
    script = textwrap.dedent("""
        import signal

        from PyQt6.QtCore import QCoreApplication, QTimer
        from pyqt_reactive.process_signals import QtProcessSignalRelay

        application = QCoreApplication([])
        relay = QtProcessSignalRelay(application)
        QTimer.singleShot(10, lambda: signal.raise_signal(signal.SIGINT))
        raise SystemExit(application.exec())
        """)
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        filter(None, (str(source_root), environment.get("PYTHONPATH")))
    )

    result = subprocess.run(
        (sys.executable, "-c", script),
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
        check=False,
    )

    assert result.returncode == 130
    assert "KeyboardInterrupt" not in result.stderr
