"""Subprocess-backed log highlighting client."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from dataclasses import dataclass
from typing import Optional, List, Tuple


@dataclass
class HighlightedSegmentDTO:
    start: int
    length: int
    color: Tuple[int, int, int]
    bold: bool = False


class LogHighlightClient:
    _proc: Optional[subprocess.Popen] = None
    _lock = threading.Lock()

    @classmethod
    def _ensure_process(cls) -> subprocess.Popen:
        if cls._proc and cls._proc.poll() is None:
            return cls._proc

        cls._proc = subprocess.Popen(
            [sys.executable, "-m", "pyqt_reactive.utils.log_highlighter"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        return cls._proc

    @classmethod
    def parse_line(cls, text: str) -> Optional[List[HighlightedSegmentDTO]]:
        try:
            with cls._lock:
                proc = cls._ensure_process()
                if not proc.stdin or not proc.stdout:
                    return None

                payload = json.dumps({"text": text}, ensure_ascii=True)
                proc.stdin.write(payload + "\n")
                proc.stdin.flush()

                line = proc.stdout.readline()
                if not line:
                    return None
                data = json.loads(line)
                segments = []
                for seg in data.get("segments", []):
                    segments.append(
                        HighlightedSegmentDTO(
                            start=seg["start"],
                            length=seg["length"],
                            color=tuple(seg["color"]),
                            bold=seg.get("bold", False),
                        )
                    )
                return segments
        except Exception:
            return None

    @classmethod
    def is_available(cls) -> bool:
        try:
            proc = cls._ensure_process()
            return proc.poll() is None
        except Exception:
            return False

    @classmethod
    def shutdown(cls) -> None:
        if not cls._proc:
            return
        try:
            cls._proc.terminate()
            cls._proc.wait(timeout=1)
        except Exception:
            try:
                cls._proc.kill()
            except Exception:
                pass
        finally:
            cls._proc = None
