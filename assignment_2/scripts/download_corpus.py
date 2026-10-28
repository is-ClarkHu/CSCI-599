"""Download every corpus PDF listed in corpus/manifest.json into corpus/raw/."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx


ROOT = Path(__file__).resolve().parents[1]


def load_manifest(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["documents"]


def target_path(raw_dir: Path, doc: dict) -> Path:
    return raw_dir / f"{doc['id']}.pdf"


def _encoded(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit(parts._replace(path=quote(parts.path)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="re-download existing files")
    args = parser.parse_args()

    raw_dir = ROOT / "corpus" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    failures = 0
    started = time.perf_counter()
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": "csci599-a2-corpus/1.0"}) as client:
        for doc in load_manifest(ROOT / "corpus" / "manifest.json"):
            path = target_path(raw_dir, doc)
            if path.exists() and not args.force:
                print(f"skip {doc['id']} (exists)")
                continue
            response = client.get(_encoded(doc["url"]))
            if response.status_code != 200 or not response.content.startswith(b"%PDF"):
                print(f"FAIL {doc['id']}: HTTP {response.status_code}", file=sys.stderr)
                failures += 1
                continue
            path.write_bytes(response.content)
            print(f"ok   {doc['id']} ({len(response.content) // 1024} KB)")
    print(f"done in {time.perf_counter() - started:.1f}s, failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
