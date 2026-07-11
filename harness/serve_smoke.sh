#!/usr/bin/env bash
# Day 0 smoke: Qwen3-8B single-GPU on pinned image, all defaults.
# Purpose: verify SM120 works, record which attention backend vLLM picks.
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-8B}"
GPU="${GPU:-0}"
PORT="${PORT:-8000}"
NAME="${NAME:-vllm-smoke}"

docker run --rm --name "$NAME" \
  --gpus "\"device=$GPU\"" \
  --ipc=host \
  -p "$PORT":8000 \
  -v "$HOME/.cache/huggingface:/root/.cache/huggingface" \
  -e HF_HUB_OFFLINE=1 \
  vllm/vllm-openai:v0.24.0 \
  "$MODEL"
