# Benchmarks

## Gateway overhead

The Go gateway is an edge layer, so its value is bounded by how much latency it
adds. The claim is sub-10ms P99 overhead versus calling FastAPI directly.

Not yet measured. `scripts/bench.sh` from PLAN.md Phase 1 is still to be
written, so no numbers are recorded here — inventing them would be worse than
leaving the section empty.

## Running a comparison

Method: identical request to both paths, provider mocked or a cheap model
targeted, enough samples for a stable P99.

```bash
# Path A — through the gateway
BASE=http://localhost:8080

# Path B — direct to FastAPI, with a valid Bearer key
BASE=http://localhost:8000
```

Then compare:

```bash
for i in $(seq 1 200); do
  curl -s -o /dev/null -w '%{time_total}\n' \
    -X POST $BASE/v1/chat/completions \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $LUNAIR_KEY" \
    -d '{"model":"auto/cheap","messages":[{"role":"user","content":"ping"}],"max_tokens":1}'
done | sort -n | awk '{a[NR]=$1} END {printf "p50=%.1fms p99=%.1fms\n", a[int(NR*0.5)]*1000, a[int(NR*0.99)]*1000}'
```

Gateway-internal latency is already tracked per route:

```bash
curl -s http://localhost:8080/metrics | grep lunair_gateway_latency_seconds
```

## Concurrency

PLAN.md targets 100 concurrent requests comparing the two paths. That belongs
in `scripts/bench.sh` with `scripts/bench-results.json` as output.

Method notes for when it lands:

- Warm up before measuring; first request pays import and connection setup.
- Test the gateway and direct paths under identical load, not sequentially.
- Streaming (`stream: true`) and non-streaming are different code paths —
  `FlushInterval: -1` changes buffering behaviour. Measure both.
- Provider latency will dominate the total and swamp the gateway's contribution.
  Mock the provider to isolate edge overhead, and measure real traffic
  separately.