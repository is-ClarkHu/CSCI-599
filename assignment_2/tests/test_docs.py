from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_architecture_covers_required_sections() -> None:
    text = read("docs/architecture.md")
    for needle in ("```mermaid", "GraphState", "Routing table", "Chunking", "k = 5",
                   "Augmentation prompt", "MCP tool sharing", "Stateless", "decide_next"):
        assert needle in text, needle


def test_evaluation_reports_numbers() -> None:
    text = read("docs/evaluation.md")
    for needle in ("Faithfulness", "Answer relevancy", "Context precision", "Context recall",
                   "TTFT", "Cold start", "Warm", "Cost per query", "Provider comparison"):
        assert needle in text, needle


def test_process_log_has_four_sections() -> None:
    text = read("PROCESS_LOG.md")
    for heading in ("## AI tools used", "## Development narrative", "## Verification narrative", "## What I learned"):
        assert heading in text, heading


def test_readme_has_setup_run_deploy_and_cost() -> None:
    text = read("README.md")
    for needle in ("Setup", "Run locally", "Deploy", "Providers", "Cost", "Rebuild the corpus", "Off-topic"):
        assert needle in text, needle


def test_no_placeholder_or_secret_left() -> None:
    for name in ("README.md", "docs/architecture.md", "docs/evaluation.md", "PROCESS_LOG.md"):
        text = read(name)
        assert "TODO" not in text and "TBD" not in text, name
        assert not re.search(r"\b(sk-[A-Za-z0-9_-]{20,}|tvly-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,})", text), name
