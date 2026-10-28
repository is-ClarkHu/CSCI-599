from __future__ import annotations

from pathlib import Path


STATIC = Path(__file__).resolve().parents[1] / "static"


def test_three_static_files_exist() -> None:
    for name in ("index.html", "app.js", "style.css"):
        assert (STATIC / name).is_file(), name


def test_index_references_local_assets_only() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "/static/app.js" in html and "/static/style.css" in html
    assert "http://" not in html and "https://cdn" not in html


def test_js_consumes_stream_with_fetch_and_handles_all_events() -> None:
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "fetch(" in js and "getReader" in js and "/api/chat" in js and "/health" in js
    for event in ("token", "trace", "citation", "error", "done"):
        assert f'"{event}"' in js or f"'{event}'" in js, event
    for kind in ("agent_route", "transition", "llm_route", "rag_retrieval", "mcp_tool_call", "sql_query", "worker_error"):
        assert kind in js, kind
    assert "innerHTML" not in js, "use textContent / createElement to avoid XSS"
    assert not any(fw in js for fw in ("React", "Vue", "angular", "svelte"))
