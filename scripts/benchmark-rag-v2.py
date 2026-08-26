#!/usr/bin/env python3
"""Measure Tickety OPS Tower RAG retrieval against a labelled JSONL dataset.

Each JSONL row must contain:
  {"question": "...", "expected": [{"source_type": "ticket", "source_id": "..."}]}

The script is read-only. Set TICKETY_BENCH_TOKEN for authenticated deployments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return ordered[index]


def load_dataset(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not str(row.get("question") or "").strip():
            raise ValueError(f"invalid dataset row {line_number}")
        expected = row.get("expected") or []
        if not isinstance(expected, list):
            raise ValueError(f"invalid expected list on row {line_number}")
        rows.append(row)
    if not rows:
        raise ValueError("dataset is empty")
    return rows


def request_search(base_url: str, question: str, limit: int, token: str) -> tuple[dict, float]:
    query = urllib.parse.urlencode({"q": question, "limit": limit})
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/ticket-intelligence/search?{query}",
        headers={"Authorization": f"Bearer {token}"} if token else {},
    )
    started = time.perf_counter()
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload, (time.perf_counter() - started) * 1000


def evaluate(args) -> int:
    rows = load_dataset(args.dataset)
    token = os.getenv("TICKETY_BENCH_TOKEN", "")
    latencies: list[float] = []
    recalls: list[float] = []
    reciprocal_ranks: list[float] = []
    methods: dict[str, int] = {}
    failures = 0
    for row in rows:
        try:
            payload, latency = request_search(
                args.base_url, row["question"], args.limit, token
            )
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            failures += 1
            print(
                json.dumps({
                    "query_hash": hashlib.sha256(
                        row["question"].encode("utf-8")
                    ).hexdigest(),
                    "error": type(exc).__name__,
                }),
                file=sys.stderr,
            )
            continue
        latencies.append(latency)
        results = payload.get("results") or []
        methods[str(payload.get("match_method") or "unknown")] = (
            methods.get(str(payload.get("match_method") or "unknown"), 0) + 1
        )
        actual = [
            (str(item.get("source_type")), str(item.get("source_id")))
            for item in results
        ]
        expected = {
            (str(item.get("source_type")), str(item.get("source_id")))
            for item in row.get("expected") or []
        }
        hits = [index for index, item in enumerate(actual, 1) if item in expected]
        recalls.append(len(set(actual) & expected) / len(expected) if expected else 1.0)
        reciprocal_ranks.append(1.0 / min(hits) if hits else 0.0)

    report = {
        "queries": len(rows),
        "completed": len(latencies),
        "failures": failures,
        "limit": args.limit,
        "recall_at_k": round(statistics.fmean(recalls), 6) if recalls else 0.0,
        "mrr": round(statistics.fmean(reciprocal_ranks), 6) if reciprocal_ranks else 0.0,
        "latency_ms": {
            "p50": round(percentile(latencies, 0.50), 3),
            "p95": round(percentile(latencies, 0.95), 3),
            "p99": round(percentile(latencies, 0.99), 3),
        },
        "match_methods": methods,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int, default=10, choices=range(1, 11))
    args = parser.parse_args()
    return evaluate(args)


if __name__ == "__main__":
    raise SystemExit(main())
