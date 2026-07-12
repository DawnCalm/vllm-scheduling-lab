# PROGRESS

## ▶ 下次 SESSION 开场清单（Claude 读到这里就按①②③顺序执行，做完一项划掉一项）
1. **还 Q1**：让用户口述"为什么 pin v0.24.0 而非 v0.25.0、代价是什么"（见 question-bank.md 第1题，上次漏答）。用户答→压缩纠偏，不代答。
2. **[weak] 抽查**：从 question-bank.md 标 [weak] 的题里抽 2–3 道让用户复述（重点 Q6/Q8/Q10 那条 prefill算KV vs decode复用KV 的边界线）。答好了去掉 [weak]，还虚就留着。
3. **进 Day 1 harness**：先让用户口述 workload 形状设计（长短混合比例/长度分布/模拟什么场景——这是"实验设计"归用户主导，Claude 不越俎代庖），用户给了设计再动手写脚手架。DoD：一条命令 → CSV+图。
（注：`git push --force origin main` 若上次没推成，提醒用户补推。）

## 当前状态
- Day: 0 完成 → 下次 Day 1 / 阶段: Phase 0（环境 + harness + 项目一仓库公开）
- 上次收尾: Day 0 技术清单全部完成 + 防守演练已批改（见 question-bank.md）；GitHub 仓库 https://github.com/DawnCalm/vllm-scheduling-lab 已建
- 阻塞项: `git push --force origin main` 待用户执行（commit 邮箱已重写为 827790610@qq.com）
- **Pin 版本: vLLM v0.24.0（docker `vllm/vllm-openai:v0.24.0`，2026-06-29 发布，2026-07-11 起手日选定）——全程不升级**

## 环境事实（2026-07-11 实测）
- GPU: 2× RTX PRO 6000 Blackwell **Server Edition**, 96GB ×2, SM120, driver 580.119.02, PCIe 无 NVLink
- CPU RAM: 125 GB 总量 / ~108 GB 可用 → KV offloading size 扫描上限约 60–80 GB
- 磁盘: 起手时仅剩 66 GB（85% 已用）⚠️ 14B/32B 权重暂不下载；大 CSV 注意采样
- 网络: huggingface.co 直连可用（~1.1s）
- 镜像 tag 实况: v0.24.0 只有默认版与 cu129 变体（调研文档中"cu130 系"已过时），pin 默认 tag
- 本机另有 conda env `vllm`（0.23.0），仅作应急备用，实验一律走 docker
- **GPU 并非双卡独占**（修正 CLAUDE.md 假设）: GPU 1 常驻师兄的 RL rollout 任务（TriLoRA，~21GB，低频使用）；`bevfusion-dev` 容器是用户自己的（不占 GPU 显存）。**所有正式实验固定跑 GPU 0**；若需双卡需先与师兄协调并在实验记录中注明 GPU 1 背景负载
- 项目一仓库: `~/AI-infra/nano-vllm`（当前 remote 指向上游 GeeeekExplorer/nano-vllm，用户自己的 fork/新仓库待建）

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
- **attention backend 三档验证全部通过（SM120 + v0.24.0）**:
  - FLASH_ATTN: 默认自动选中（8B 完整冒烟 + bench）
  - FLASHINFER: `--attention-backend FLASHINFER`，8B server ready + 0.6B 正面日志 `Using AttentionBackendEnum.FLASHINFER backend.` + 推理正确
  - TRITON_ATTN: 同 flag，8B 正面日志 + 推理正确
  - 坑三连（全部记入面试素材）: ① `VLLM_ATTENTION_BACKEND` 环境变量在 v0.24.0 已移除，静默不生效，正确方式是 `--attention-backend` flag（另有新式 `--attention-config`）；② 显式指定与自动选择的日志行不同（cuda.py:420 vs :480），验证脚本要认对签名；③ FLASHINFER 首启含 JIT 编译，启动等待要给足（>5min）
- conda env 验证（用户要求）: env 里实际是 0.24.0+cu130 与 pin 版本同源同版，但缺 `flashinfer-jit-cache` 包导致 SM120 上 `sm75 or higher` 误报崩溃 → 实验一律走 docker；env 的价值 = 本地直读同版源码（溯源用）
- 待办: GitHub 仓库创建+push（等用户 `gh auth login`）；项目一仓库整理（用户）；磁盘仅剩 ~21GB 需留意；Day 1 harness（一条命令 → CSV+图）
