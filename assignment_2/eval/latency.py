"""Measure cold vs warm latency, per-stage timing and token cost against a deployed URL.

Usage: python -m eval.latency https://<service-url>
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    ("rules", "How long is the stall count under WFDF rules?"),
    ("rules", "What happens after a contested foul?"),
    ("summary", "Summarize how WFDF and USA Ultimate differ on fouls."),
    ("stats", "How many WUGC open division gold medals has the United States won?"),
    ("stats", "Which country won the mixed division at the most recent WUGC in the database?"),
    ("news", "What is the latest WFDF news this month?"),
    ("off_topic", "Recommend a good laptop for programming."),
]


def stream(client: httpx.Client, url: str, query: str) -> dict:
    started = time.perf_counter()
    ttft = None
    events: list[tuple[str, dict]] = []
    buffer = ""
    with client.stream("POST", f"{url}/api/chat", json={"query": query}) as response:
        for text in response.iter_text():
            buffer += text
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                fields = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
                if "event" not in fields:
                    continue
                event, data = fields["event"], json.loads(fields.get("data", "{}"))
                if event == "token" and ttft is None:
                    ttft = time.perf_counter() - started
                events.append((event, data))
    total = time.perf_counter() - started
    traces = [d for e, d in events if e == "trace"]
    llm = defaultdict(lambda: {"ms": 0, "input_tokens": 0, "output_tokens": 0})
    for t in traces:
        if t["kind"] == "llm_done":
            key = f"{t['provider']}:{t['model']}"
            llm[key]["ms"] += t["elapsed_ms"]
            llm[key]["input_tokens"] += t["input_tokens"]
            llm[key]["output_tokens"] += t["output_tokens"]
    done = next((d for e, d in events if e == "done"), {})
    return {
        "client_ttft_s": round(ttft, 3) if ttft else None,
        "client_total_s": round(total, 3),
        "server_ttft_ms": done.get("ttft_ms"),
        "server_total_ms": done.get("elapsed_ms"),
        "retrieval_ms": sum(t.get("elapsed_ms", 0) for t in traces if t["kind"] == "rag_retrieval"),
        "web_ms": sum(t.get("elapsed_ms", 0) for t in traces if t["kind"] == "mcp_tool_call"),
        "llm": dict(llm),
        "errors": [d for e, d in events if e == "error"],
    }


EMBEDDING_KEY = "openai:text-embedding-3-small"


def cost(llm: dict, prices: dict, query: str, used_retrieval: bool) -> tuple[float, list[str]]:
    """Return (usd, problems). Missing prices or missing token usage make the measurement incomplete."""

    table = prices["per_million_tokens"]
    problems: list[str] = []
    total = 0.0
    for key, usage in llm.items():
        price = table.get(key)
        if price is None:
            problems.append(f"no price for {key}")
            continue
        if usage["input_tokens"] == 0 and usage["output_tokens"] == 0:
            problems.append(f"no token usage reported by {key}")
        total += usage["input_tokens"] / 1e6 * price["input"] + usage["output_tokens"] / 1e6 * price["output"]
    if used_retrieval:  # one query embedding per retrieval; ~4 characters per token estimate
        price = table.get(EMBEDDING_KEY)
        if price is None:
            problems.append(f"no price for {EMBEDDING_KEY}")
        else:
            total += max(1, len(query) // 4) / 1e6 * price["input"]
    return round(total, 6), problems


def main(url: str) -> int:
    prices = json.loads((ROOT / "eval" / "prices.json").read_text())
    runs = []
    with httpx.Client(timeout=300) as client:
        for category, query in QUERIES:
            first = stream(client, url, query)
            second = stream(client, url, query)
            for label, run in (("first", first), ("warm", second)):
                usd, problems = cost(run["llm"], prices, query, run["retrieval_ms"] > 0)
                run.update({"category": category, "query": query, "run": label, "cost_usd": usd,
                            "cost_complete": not problems, "cost_problems": problems})
                runs.append(run)
                print(f"{category:9s} {label:5s} ttft={run['client_ttft_s']}s total={run['client_total_s']}s "
                      f"cost=${run['cost_usd']}")
    warm = [r for r in runs if r["run"] == "warm" and r["client_ttft_s"]]
    summary = {
        "warm_median_ttft_s": statistics.median(r["client_ttft_s"] for r in warm),
        "warm_median_total_s": statistics.median(r["client_total_s"] for r in warm),
        "median_cost_usd": statistics.median(r["cost_usd"] for r in runs if r["category"] != "off_topic"),
        "cost_complete": all(r["cost_complete"] for r in runs),
        "prices_checked_on": prices["checked_on"],
    }
    if not summary["cost_complete"]:
        print("WARNING: cost is incomplete:", sorted({p for r in runs for p in r["cost_problems"]}))
    out = ROOT / "eval" / "results" / "latency.json"
    out.write_text(json.dumps({"url": url, "summary": summary, "runs": runs}, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1].rstrip("/")))
