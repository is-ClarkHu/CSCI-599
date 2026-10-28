from __future__ import annotations

import json
from pathlib import Path


QUESTIONS = Path(__file__).resolve().parents[1] / "eval" / "questions.jsonl"


def test_question_set_is_fixed_and_complete() -> None:
    rows = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(rows) == 25
    assert len({r["id"] for r in rows}) == 25
    for row in rows:
        assert row["question"].strip() and row["reference"].strip(), row["id"]
        assert " p." in row["source"], row["id"]
