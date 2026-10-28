from __future__ import annotations

import json
import time
from typing import Any

from langgraph.config import get_stream_writer

from app.types import Citation


def emit(event: str, data: dict[str, Any]) -> None:
    """Write a custom stream event when running inside a LangGraph node; no-op otherwise."""

    try:
        writer = get_stream_writer()
    except Exception:
        return
    writer({"event": event, "data": data})


def trace(kind: str, node: str, **detail: Any) -> None:
    emit("trace", {"kind": kind, "node": node, "ts": int(time.time() * 1000), **detail})


def token(text: str, node: str) -> None:
    emit("token", {"text": text, "node": node})


def citation(item: Citation) -> None:
    emit("citation", dict(item))


def sse_frame(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
