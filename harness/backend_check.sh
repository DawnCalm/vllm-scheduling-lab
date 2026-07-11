#!/usr/bin/env bash
# Day 0: verify a given attention backend starts and serves on SM120.
# Usage: backend_check.sh FLASHINFER|TRITON_ATTN|FLASH_ATTN [GPU]
set -uo pipefail

BE="$1"
GPU="${2:-1}"
PORT=8001
NAME="vllm-be-check"

docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" \
  --gpus "\"device=$GPU\"" \
  --ipc=host \
  -p "$PORT":8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  -e HF_HUB_OFFLINE=1 \
  vllm/vllm-openai:v0.24.0 \
  Qwen/Qwen3-8B --attention-backend "$BE" >/dev/null

echo "[$BE] container started on GPU $GPU, waiting for /health ..."
# FLASHINFER 首启含 JIT 编译，可能远超 5 分钟，默认等 15 分钟
for i in $(seq 1 $(( ${WAIT_SECS:-900} / 2 ))); do
  if curl -sf "http://localhost:$PORT/health" >/dev/null 2>&1; then break; fi
  if ! docker ps -q -f name="$NAME" | grep -q .; then
    echo "[$BE] FAILED: container exited during startup; last error lines:"
    docker logs "$NAME" 2>&1 | grep -iE "error|raise|not supported|no module|assert" | tail -10
    docker logs "$NAME" 2>&1 | tail -15 > "/tmp/backend_check_${BE}_fail.log"
    echo "[$BE] full tail saved to /tmp/backend_check_${BE}_fail.log"
    docker rm -f "$NAME" >/dev/null 2>&1
    exit 1
  fi
  sleep 2
done

echo "[$BE] backend line from log:"
# 显式 --attention-backend 时日志是 "Using AttentionBackendEnum.X backend."（cuda.py:420）
# 自动选择时是 "Using X attention backend out of potential backends"（cuda.py:480）
BACKEND_LINE=$(docker logs "$NAME" 2>&1 | grep -m1 -E "Using .* backend\.|Using .* attention backend")
echo "$BACKEND_LINE"
if ! echo "$BACKEND_LINE" | grep -qE "Using (AttentionBackendEnum\.)?$BE( attention)? backend"; then
  echo "[$BE] FAILED: selected backend does not match requested"
  docker logs "$NAME" 2>&1 | tail -15 > "/tmp/backend_check_${BE}_fail.log"
  docker rm -f "$NAME" >/dev/null 2>&1
  exit 1
fi

RESP=$(curl -s "http://localhost:$PORT/v1/completions" -H "Content-Type: application/json" \
  -d '{"model":"Qwen/Qwen3-8B","prompt":"2+2=","max_tokens":8,"temperature":0}')
echo "[$BE] completion output: $(echo "$RESP" | python3 -c "import sys,json; print(json.load(sys.stdin)['choices'][0]['text'].strip())" 2>&1)"

docker rm -f "$NAME" >/dev/null
echo "[$BE] PASS"
