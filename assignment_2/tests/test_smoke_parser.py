from __future__ import annotations

from scripts.smoke_test import parse_sse


def test_parse_sse_splits_frames() -> None:
    raw = 'event: trace\ndata: {"kind": "agent_route"}\n\nevent: token\ndata: {"text": "hi"}\n\nevent: done\ndata: {}\n\n'
    assert parse_sse(raw) == [("trace", {"kind": "agent_route"}), ("token", {"text": "hi"}), ("done", {})]


def test_parse_sse_keeps_unicode_line_separators_inside_json() -> None:
    raw = 'event: token\ndata: {"text": "a b"}\n\n'
    assert parse_sse(raw) == [("token", {"text": "a b"})]
