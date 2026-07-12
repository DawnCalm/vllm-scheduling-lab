#!/usr/bin/env bash
# One-command reproducible load run: serve (reuse) -> poll /metrics -> load -> plot.
#
# Usage:
#   harness/run.sh OUTDIR [extra run_load.py args...]
# Example (Day 1 smoke):
#   harness/run.sh /tmp/demo --n-long 2 --n-short 3 --long-input 4000
# Example (full A1 point):
#   harness/run.sh experiments/a1-preemption/results/burst-20x100 --n-long 20 --n-short 100
#
# Env overrides: MODEL, GPU, PORT, IMAGE, CONDA_ENV, POLL_INTERVAL, FRESH=1
set -uo pipefail

OUTDIR="${1:?usage: run.sh OUTDIR [run_load args...]}"; shift || true
MODEL="${MODEL:-Qwen/Qwen3-8B}"
GPU="${GPU:-0}"
PORT="${PORT:-8000}"
IMAGE="${IMAGE:-vllm/vllm-openai:v0.24.0}"
CONDA_ENV="${CONDA_ENV:-vllm}"
POLL_INTERVAL="${POLL_INTERVAL:-0.25}"
NAME="vllm-harness"
BASE_URL="http://localhost:${PORT}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY() { conda run --no-capture-output -n "$CONDA_ENV" python "$@"; }

mkdir -p "$OUTDIR"

# --- 1. server: reuse a healthy container, else (re)start and wait -------------
if [[ "${FRESH:-0}" == "1" ]]; then docker rm -f "$NAME" >/dev/null 2>&1; fi
if ! curl -sf "$BASE_URL/health" >/dev/null 2>&1; then
  echo "[run] starting $IMAGE on GPU $GPU (model=$MODEL) ..."
  docker rm -f "$NAME" >/dev/null 2>&1
  docker run -d --name "$NAME" \
    --gpus "\"device=$GPU\"" --ipc=host -p "$PORT":8000 \
    -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
    -e HF_HUB_OFFLINE=1 \
    "$IMAGE" "$MODEL" >/dev/null
  echo -n "[run] waiting for /health "
  for _ in $(seq 1 300); do
    if curl -sf "$BASE_URL/health" >/dev/null 2>&1; then echo " ready"; break; fi
    if ! docker ps -q -f name="$NAME" | grep -q .; then
      echo " FAILED"; docker logs "$NAME" 2>&1 | tail -20; exit 1
    fi
    echo -n "."; sleep 2
  done
else
  echo "[run] reusing healthy server at $BASE_URL"
fi
curl -sf "$BASE_URL/health" >/dev/null || { echo "[run] server not healthy"; exit 1; }

# --- 2. metrics poller in background ------------------------------------------
PY "$HERE/metrics_poll.py" --base-url "$BASE_URL" --interval "$POLL_INTERVAL" \
   --out "$OUTDIR/metrics.csv" &
POLL_PID=$!
trap 'kill -TERM $POLL_PID 2>/dev/null' EXIT
sleep 1  # capture a short idle baseline before load

# --- 3. load ------------------------------------------------------------------
PY "$HERE/run_load.py" --base-url "$BASE_URL" --model "$MODEL" \
   --out "$OUTDIR/requests.csv" "$@"

# --- 4. stop poller, plot -----------------------------------------------------
sleep 1
kill -TERM $POLL_PID 2>/dev/null; wait $POLL_PID 2>/dev/null; trap - EXIT
PY "$HERE/plot.py" --requests "$OUTDIR/requests.csv" \
   --metrics "$OUTDIR/metrics.csv" --outdir "$OUTDIR/plots" --tag "$(basename "$OUTDIR")"

echo "[run] artifacts:"
echo "  $OUTDIR/requests.csv  $OUTDIR/metrics.csv"
echo "  $OUTDIR/plots/timeline.png  $OUTDIR/plots/ttft_by_class.png"
