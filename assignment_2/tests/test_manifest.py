from __future__ import annotations

from pathlib import Path

from scripts.download_corpus import load_manifest, target_path


MANIFEST = Path(__file__).resolve().parents[1] / "corpus" / "manifest.json"


def test_manifest_is_well_formed() -> None:
    docs = load_manifest(MANIFEST)
    assert len(docs) >= 12
    ids = [doc["id"] for doc in docs]
    assert len(ids) == len(set(ids))
    for doc in docs:
        assert doc["url"].startswith("https://")
        assert doc["title"] and doc["publisher"] and doc["version"]


def test_target_path_uses_id(tmp_path: Path) -> None:
    assert target_path(tmp_path, {"id": "wfdf-rules-2025"}) == tmp_path / "wfdf-rules-2025.pdf"
