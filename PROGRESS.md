# PROGRESS

## 当前状态
- Day: 0 / 阶段: Phase 0（环境 + harness + 项目一仓库公开）
- 上次收尾: 无（今天起手）
- 阻塞项: 无
- **Pin 版本: vLLM v0.24.0（docker `vllm/vllm-openai:v0.24.0`，2026-06-29 发布，2026-07-11 起手日选定）——全程不升级**

## 环境事实（2026-07-11 实测）
- GPU: 2× RTX PRO 6000 Blackwell **Server Edition**, 96GB ×2, SM120, driver 580.119.02, PCIe 无 NVLink
- CPU RAM: 125 GB 总量 / ~108 GB 可用 → KV offloading size 扫描上限约 60–80 GB
- 磁盘: 起手时仅剩 66 GB（85% 已用）⚠️ 14B/32B 权重暂不下载；大 CSV 注意采样
- 网络: huggingface.co 直连可用（~1.1s）
- 镜像 tag 实况: v0.24.0 只有默认版与 cu129 变体（调研文档中"cu130 系"已过时），pin 默认 tag
- 本机另有 conda env `vllm`（0.23.0），仅作应急备用，实验一律走 docker

## 日志（倒序）

### 2026-07-11 (Day 0)
- 完成: 环境摸底；pin v0.24.0（当日 v0.25.0 刚发布零 soak，弃）；git init + 骨架；镜像+权重落盘；**Qwen3-8B 单卡冒烟通过**；`vllm bench serve` 跑通；/metrics 抢占计数器实名确认
- 实证发现（全部来自 v0.24.0 容器实测，非记忆）:
  - 容器内 torch 2.11.0+**cu130**（默认 tag 即 cu130 构建）
  - **SM120 默认 attention backend = FLASH_ATTN**（候选四档: FLASH_ATTN / FLASHINFER / TRITON_ATTN / FLEX_ATTENTION）——调研预期的"FlashInfer 优先"与实际不符
  - 抢占计数器: `vllm:num_preemptions_total`；核心观测: `vllm:kv_cache_usage_perc`、`vllm:num_requests_waiting(_by_reason)`、直方图 `vllm:time_to_first_token_seconds` / `vllm:request_queue_time_seconds` / `vllm:request_prefill_time_seconds` / `vllm:request_decode_time_seconds`
  - Qwen3-8B 默认配置: max_model_len 40960、chunked prefill on (max_num_batched_tokens=8192)、KV cache 70.65 GiB = 514,464 tokens、"Maximum concurrency 12.56x"
  - `vllm bench serve` 注意: 默认**不再** temperature=0，复现实验必须显式 `--temperature`；有 `--seed`、`--save-result`、`--percentile-metrics`
- 基线数字（哨兵值，非正式实验）: 512in/128out×50req 并发10 → median TTFT 190ms / TPOT 12.4ms / 722 tok/s output
- 数据: 无正式数据（环境日）；脚本 harness/serve_smoke.sh、harness/backend_check.sh
- 结论一句话: v0.24.0 在 SM120 上开箱即用，但默认 backend 是 FLASH_ATTN 而非调研预期的 FlashInfer——一切以容器实测为准的原则第一天就兑现了价值
- 待办: FLASHINFER / TRITON_ATTN 两档验证（进行中）；磁盘仅剩 ~21GB 需留意；项目一仓库整理（用户）
