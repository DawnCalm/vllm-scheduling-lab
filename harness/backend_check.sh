#!/usr/bin/env bash
# Day 0: verify a given attention backend starts and serves on SM120.
# Usage: backend_check.sh FLASHINFER|TRITON_ATTN|FLASH_ATTN [GPU]
set -uo pipefail

BE="$1"
GPU="${2:-1}"
PORT=8001
NAME="vllm-be-check"

docker rm -f "$NAME" >/dev/null 2>&1
docker run --rm -d --name "$NAME" \
  --gpus "\"device=$GPU\"" \
  --ipc=host \
  -p "$PORT":8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  -e HF_HUB_OFFLINE=1 \
  -e VLLM_ATTENTION_BACKEND="$BE" \
  vllm/vllm-openai:v0.24.0 \
  Qwen/Qwen3-8B >/dev/null

echo "[$BE] container started on GPU $GPU, waiting for /health ..."
for i in $(seq 1 150); do
  if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then break; fi
  if ! docker ps -q -f name="$NAME" | grep -q .; then
    echo "[$BE] FAILED: container exited during startup"
    docker logs "$NAME" 2>&1 | grep -iE "error|traceback|not supported" | tail -5
    exit 1
  fi
  sleep 2
done

echo "[$BE] backend line from log:"
docker logs "$NAME" 2>&1 | grep -m1 -i "attention backend"

RESP=$(curl -s "http://localhost:$PORT/v1/completions" -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen3-8B","prompt":"2+2=","max_tokens":8,"temperature":0}')
echo "[$BE] completion output: $(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['text'].strip())" 2>&1)"

docker stop "$NAME" >/dev/null
echo "[$BE] PASS"
