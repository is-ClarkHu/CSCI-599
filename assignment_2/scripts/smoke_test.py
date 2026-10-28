"""Exercise a deployed service with one query per path and assert the expected trace evidence."""

from __future__ import annotations

import json
import sys
import time

import httpx


CASES = [
    ("rules", "In WFDF rules, how many seconds does the marker count before a stall?",
     lambda ev: any(e == "trace" and d.get("kind") == "rag_retrieval" for e, d in ev)),
    ("summary", "Summarize the main differences between WFDF and USA Ultimate rules on fouls.",
     lambda ev: any(e == "trace" and d.get("kind") == "llm_route" and d.get("node") == "summary" for e, d in ev)),
    ("stats", "How many gold medals has Japan won in the women's division at WUGC?",
     lambda ev: any(e == "trace" and d.get("kind") == "sql_query" for e, d in ev)),
    ("news", "What is the latest news from WFDF this month?",
     lambda ev: any(e == "trace" and d.get("kind") == "mcp_tool_call" for e, d in ev)),
    ("off_topic", "What's a good recipe for banana bread?",
     lambda ev: any(e == "trace" and d.get("reason") == "off-topic, no worker" for e, d in ev)),
    # MCP tool sharing evidence: the SAME tool (tavily_extract) is invoked by two different agents.
    ("mcp_share", "Summarize the latest WFDF news this month in three bullet points.",
     lambda ev: {d.get("node") for e, d in ev if e == "trace" and d.get("kind") == "mcp_tool_call"
                 and d.get("tool") == "tavily_extract" and d.get("ok")} >= {"research", "summary"}),
]


def parse_sse(text: str) -> list[tuple[str, dict]]:
    frames = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        if "event" in fields:
            frames.append((fields["event"], json.loads(fields.get("data", "{}"))))
    return frames


def main(base_url: str) -> int:
    failures = 0
    with httpx.Client(timeout=300) as client:
        health = client.get(f"{base_url}/health").json()
        components = health["components"]
        print("health:", health["status"], {k: v.get("ok") for k, v in components.items()})
        health_ok = (health["status"] == "ok" and components["rag_index"]["chunks"] > 0
                     and {"tavily_search", "tavily_extract"} <= set(components["tavily_mcp"]["tools"])
                     and components["medals_db"]["rows"] > 0)
        print(f"[{'PASS' if health_ok else 'FAIL'}] health")
        failures += 0 if health_ok else 1
        for name, query, check in CASES:
            started = time.perf_counter()
            events = parse_sse(client.post(f"{base_url}/api/chat", json={"query": query}).text)
            tokens = "".join(d.get("text", "") for e, d in events if e == "token")
            providers = sorted({d["provider"] for e, d in events if e == "trace" and d.get("kind") == "llm_route"})
            ok = check(events) and events[-1][0] == "done" and tokens.strip() and not any(e == "error" for e, _ in events)
            failures += 0 if ok else 1
            print(f"[{'PASS' if ok else 'FAIL'}] {name:9s} {time.perf_counter() - started:5.1f}s providers={providers} "
                  f"answer={tokens[:90]!r}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1].rstrip("/")))
