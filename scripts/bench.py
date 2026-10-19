#!/usr/bin/env python3
"""Load generator for the LunAIR gateway benchmark.

Measures edge overhead only: it hits an endpoint that does not reach a provider,
so the numbers isolate gateway cost instead of being swamped by upstream LLM
latency. Standard library only, so there is nothing to install.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from urllib.parse import urlparse


@dataclass
class Sample:
    latency_ms: float
    status: int
    error: str | None = None


@dataclass
class Result:
    label: str
    target: str
    concurrency: int
    latency: dict[str, float] = field(default_factory=dict)
    total_requests: int = 0
    errors: int = 0
    wall_seconds: float = 0.0

    @property
    def rps(self) -> float:
        return self.total_requests / self.wall_seconds if self.wall_seconds else 0.0


def parse_url(raw: str) -> tuple[str, int, str]:
    parsed = urlparse(raw if "://" in raw else f"http://{raw}")
    scheme = parsed.scheme or "http"
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if scheme == "https" else 80)
    path = parsed.path or "/"
    return scheme, host, port, path


def make_worker(
    scheme: str,
    host: str,
    port: int,
    path: str,
    remaining: list[int],
    samples: list[Sample],
    lock: threading.Lock,
    headers: dict[str, str],
    stop: threading.Event,
) -> None:
    conn_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection

    while not stop.is_set():
        with lock:
            if not remaining:
                return
            remaining.pop()

        conn = None
        started = time.perf_counter()
        status = 0
        error: str | None = None

        try:
            # A fresh connection per request keeps keep-alive effects out of
            # the comparison; both paths are measured the same way.
            conn = conn_cls(host, port, timeout=30)
            conn.request("GET", path, headers=headers)
            response = conn.getresponse()
            status = response.status
            response.read()
        except Exception as exc:
            error = type(exc).__name__
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

        elapsed_ms = (time.perf_counter() - started) * 1000.0

        with lock:
            samples.append(Sample(latency_ms=elapsed_ms, status=status, error=error))


def run_once(
    label: str,
    base_url: str,
    path: str,
    total: int,
    concurrency: int,
    warmup: int,
    headers: dict[str, str],
) -> Result:
    scheme, host, port, full_path = parse_url(base_url)
    if path and path != "/":
        full_path = f"{full_path.rstrip('/')}{path}"

    lock = threading.Lock()
    samples: list[Sample] = []
    stop = threading.Event()

    # Warmup connections are measured but discarded so TLS/DNS/cold-start
    # costs do not land in the percentiles.
    remaining = list(range(total + warmup))
    threads = [threading.Thread(target=make_worker,
                                args=(scheme, host, port, full_path, remaining,
                                      samples, lock, headers, stop),
                                daemon=True)
               for _ in range(max(1, concurrency))]
    for thread in threads:
        thread.start()

    started = time.perf_counter()
    for thread in threads:
        thread.join()
    wall = time.perf_counter() - started

    with lock:
        ordered = samples[:]
    ordered.sort(key=lambda s: s.latency_ms)

    if warmup:
        ordered = ordered[warmup:] if len(ordered) > warmup else ordered

    latencies = [s.latency_ms for s in ordered]
    errors = sum(1 for s in ordered if s.error or s.status >= 400)

    if not latencies:
        return Result(label=label, target=base_url + full_path, concurrency=concurrency)

    def percentile(fraction: float) -> float:
        if not latencies:
            return 0.0
        index = min(len(latencies) - 1, int(round(fraction * (len(latencies) - 1))))
        return latencies[index]

    result = Result(
        label=label,
        target=base_url + full_path,
        concurrency=concurrency,
        total_requests=len(ordered),
        errors=errors,
        wall_seconds=wall,
    )
    result.latency = {
        "p50_ms": round(percentile(0.50), 2),
        "p95_ms": round(percentile(0.95), 2),
        "p99_ms": round(percentile(0.99), 2),
        "mean_ms": round(statistics.fmean(latencies), 2),
        "max_ms": round(max(latencies), 2),
        "min_ms": round(min(latencies), 2),
    }
    return result


def check_health(label: str, base_url: str) -> None:
    scheme, host, port, _ = parse_url(base_url)
    conn_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    try:
        conn = conn_cls(host, port, timeout=5)
        conn.request("GET", "/health")
        response = conn.getresponse()
        response.read()
        conn.close()
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}")
        print(f"  {label} ok ({base_url})")
    except Exception as exc:
        print(f"error: {label} is not reachable at {base_url} ({exc})", file=sys.stderr)
        print("       start the stack first: docker compose --profile gateway up -d",
              file=sys.stderr)
        raise SystemExit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--go-url", default=os.environ.get("GO_URL", "http://localhost:8080"))
    parser.add_argument("--direct-url",
                        default=os.environ.get("DIRECT_URL", "http://localhost:8000"))
    parser.add_argument("--path", default=os.environ.get("BENCH_PATH", "/v1/models"))
    parser.add_argument("-n", type=int, default=int(os.environ.get("REQUESTS", 500)))
    parser.add_argument("-c", type=int, default=int(os.environ.get("CONCURRENCY", 100)))
    parser.add_argument("--warmup", type=int, default=int(os.environ.get("WARMUP", 50)))
    parser.add_argument("-o", "--out",
                        default=os.environ.get(
                            "BENCH_OUT",
                            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                         "bench-results.json"),
                        ))
    args = parser.parse_args()

    headers = {"User-Agent": "lunair-bench/1.0"}
    key = os.environ.get("LUNAIR_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"

    print("preflight:")
    check_health("gateway", args.go_url)
    check_health("fastapi", args.direct_url)

    print(f"\nrunning {args.n} requests at concurrency {args.c} "
          f"(+{args.warmup} warmup) against {args.path}\n")

    results = []
    for label, url in (("go", args.go_url), ("fastapi_only", args.direct_url)):
        result = run_once(label, url, args.path, args.n, args.c, args.warmup, headers)
        results.append(result)
        lat = result.latency
        print(f"  {label:<14} p50={lat.get('p50_ms', 0):7.2f}ms  "
              f"p95={lat.get('p95_ms', 0):7.2f}ms  "
              f"p99={lat.get('p99_ms', 0):7.2f}ms  "
              f"rps={result.rps:8.1f}  errors={result.errors}")

    timestamp = datetime.now(timezone.utc).isoformat()
    overhead = results[0].latency.get("p99_ms", 0) - results[1].latency.get("p99_ms", 0)

    doc = {
        "generated_at": timestamp,
        "requests": args.n,
        "concurrency": args.c,
        "benchmark_note": (
            "Edge overhead measured on an endpoint with no provider call, so "
            "upstream LLM latency does not mask the gateway's own cost. Run with "
            "BENCH_PATH=/v1/chat/completions for end-to-end numbers."
        ),
        "p99_overhead_ms": round(overhead, 2),
        "results": [
            {
                "mode": r.label,
                "target": r.target,
                "concurrency": r.concurrency,
                "timestamp": timestamp,
                "latency": {
                    **r.latency,
                    "rps": round(r.rps, 2),
                    "requests": r.total_requests,
                    "errors": r.errors,
                },
            }
            for r in results
        ],
    }

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)
        fh.write("\n")

    print(f"\np99 overhead: {overhead:+.2f} ms")
    print(f"written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())