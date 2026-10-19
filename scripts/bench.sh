#!/usr/bin/env bash
# Benchmark the Go gateway against the direct FastAPI path.
#
#   ./scripts/bench.sh                          # 500 requests, 100 concurrent
#   REQUESTS=2000 CONCURRENCY=250 ./scripts/bench.sh
#   BENCH_PATH=/v1/chat/completions LUNAIR_KEY=sk-... ./scripts/bench.sh
#
# Thin wrapper around bench.py so the documented entry point stays stable.
# Standard library only — nothing to install.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

exec python3 "$DIR/bench.py" "$@"