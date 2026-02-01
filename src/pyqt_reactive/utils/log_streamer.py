"""Stream log file lines as JSONL chunks for UI consumption."""

import argparse
import json
import sys
from collections import deque
from pathlib import Path
import re


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def tail_lines(path: Path, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []

    buf: deque[str] = deque(maxlen=max_lines)
    with open(path, "r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            buf.append(line.rstrip("\n"))
    return list(buf)


_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2},\d{3}")
_LOG_LEVEL_RE = re.compile(r"\b(ERROR|WARNING|INFO|DEBUG|CRITICAL)\b")
_LOGGER_NAME_RE = re.compile(r" - ([\w\.]+) - ")
_FILE_PATH_RE = re.compile(r"(?:/[\w\-\.]+)+\.py")
_PYTHON_STRING_RE = re.compile(r"[\"'](?:[^\"'\\]|\\.)*[\"']")
_NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _segments_for_line(text: str) -> list[dict]:
    segments = []

    match = _TIMESTAMP_RE.match(text)
    if match:
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": (105, 105, 105)})

    for match in _LOG_LEVEL_RE.finditer(text):
        level = match.group(1)
        if level in ("ERROR", "CRITICAL"):
            color = (255, 85, 85)
        elif level == "WARNING":
            color = (255, 140, 0)
        else:
            color = (100, 160, 210)
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": color, "bold": True})

    for match in _LOGGER_NAME_RE.finditer(text):
        segments.append({"start": match.start(1), "length": match.end(1) - match.start(1), "color": (147, 112, 219)})

    for match in _FILE_PATH_RE.finditer(text):
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": (34, 139, 34)})

    for match in _PYTHON_STRING_RE.finditer(text):
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": (206, 145, 120)})

    for match in _NUMBER_RE.finditer(text):
        segments.append({"start": match.start(), "length": match.end() - match.start(), "color": (181, 206, 168)})

    return segments


def _build_html(text: str) -> str:
    segments = sorted(_segments_for_line(text), key=lambda s: s["start"])
    cursor = 0
    parts: list[str] = ["<span style=\"white-space: pre-wrap;\">"]
    text_len = len(text)

    for seg in segments:
        start = max(0, seg["start"])
        end = min(text_len, start + seg["length"])
        if end <= start or start < cursor:
            continue
        if start > cursor:
            parts.append(_escape_html(text[cursor:start]))

        r, g, b = seg["color"]
        style = f"color: rgb({r},{g},{b});"
        if seg.get("bold"):
            style += " font-weight: 700;"
        parts.append(f"<span style=\"{style}\">{_escape_html(text[start:end])}</span>")
        cursor = end

    if cursor < text_len:
        parts.append(_escape_html(text[cursor:]))

    parts.append("</span>")
    return "".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--tail-lines", type=int, default=100_000)
    parser.add_argument("--chunk-lines", type=int, default=1000)
    parser.add_argument("--html", action="store_true")
    args = parser.parse_args()

    log_path = Path(args.path)
    try:
        lines = tail_lines(log_path, args.tail_lines)
        chunk: list = []
        for line in lines:
            if args.html:
                chunk.append({"text": line, "html": _build_html(line)})
            else:
                chunk.append(line)
            if len(chunk) >= args.chunk_lines:
                emit({"type": "chunk", "lines": chunk})
                chunk = []

        if chunk:
            emit({"type": "chunk", "lines": chunk})

        emit({"type": "done"})
        return 0
    except Exception as exc:
        sys.stderr.write(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
