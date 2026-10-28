#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
import uuid

import httpx


def chat(client: httpx.Client, base_url: str, query: str, session_id: str) -> str:
    response = client.post(
        f"{base_url.rstrip('/')}/chat",
        json={"query": query, "session_id": session_id},
    )
    response.raise_for_status()
    payload = response.json()
    answer = payload.get("response")
    if not isinstance(answer, str) or not answer.strip():
        raise AssertionError(f"Invalid response payload: {payload!r}")
    return answer


def main() -> int:
    parser = argparse.ArgumentParser(description="Exercise a local or deployed agent")
    parser.add_argument("base_url", nargs="?", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    session_id = f"smoke-{uuid.uuid4().hex[:10]}"

    with httpx.Client(timeout=120) as client:
        health = client.get(f"{args.base_url.rstrip('/')}/health")
        health.raise_for_status()
        print("health:", health.json())

        first = chat(
            client,
            args.base_url,
            "Remember that my test color is amber. Reply briefly.",
            session_id,
        )
        second = chat(
            client,
            args.base_url,
            "What test color did I give you in the previous turn?",
            session_id,
        )
        weather = chat(
            client,
            args.base_url,
            "Use the weather tool to get today's weather in Los Angeles.",
            session_id,
        )
        print("turn 1:", first)
        print("memory turn:", second)
        print("weather tool:", weather)

        if "amber" not in second.lower():
            raise AssertionError("The second response did not demonstrate session memory")

    print("Smoke test passed for session", session_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
