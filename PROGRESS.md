# PROGRESS

## ▶ 下次 SESSION 开场清单（Claude 读到这里就按①②③顺序执行，做完一项划掉一项）
1. **确认 GPU 是否已释放**：`nvidia-smi` 看 GPU 0 是否还被 dzkduser 的 evorubrics 占（Day 1 时两卡各 ~80GB，只剩 ~17GB，跑不了 8B）。没释放→回到"等/协调"或先做无 GPU 的活（架构图、项目一公开）。
2. **GPU 一到手，先冒烟验证 harness**（Day 1 写完但**一行没在真服务上跑过**）：`harness/run.sh /tmp/demo --n-long 2 --n-short 3 --long-input 4000` 用小 workload 验证 4 个 API 假设：①token-id 列表当 prompt ②`min_tokens`/`ignore_eos` ③streaming 抓 TTFT ④/metrics 字段名对得上。任一不成立就地修。
3. **冒烟过了再上 A1 首个点**：`harness/run.sh experiments/a1-preemption/results/burst-20x100 --n-long 20 --n-short 100`（20长/100短=114%超线，预期触发抢占）。DoD：一条命令→CSV+图，timeline.png 里 preemptions 曲线抬头。
4. **[weak] 抽查**（若有空）：question-bank 剩余 [weak]；Q8 尾巴"TTFT 恶化归因到排队"复述一遍。
（注：`git push` 仍有 3 个 commit 未推——fetch 后 origin/main 停在 c701a2，本地领先 e52ce40/c470aab/ec5d606；用户以为推了其实没推。可能需 `--force`（重写过邮箱）。）

## 当前状态
- Day: 1 进行中（harness 代码完成但**未验证**）/ 阶段: Phase 0
- 上次收尾: Day 1 写完 harness 全部 4 部件 + run.sh 编排；但 GPU 被占无法起服务验证；Q1 补答+prefill/decode 边界焊死（见 question-bank Day 1 复查）
- **阻塞项（硬）**: GPU 0/1 各被 dzkduser 的 `evorubrics` 任务占 ~80GB（PID 3230151/3230152），各只剩 ~17GB → 8B(权重16GB)+KV 塞不下。用户选择线下协调 GPU（问 evorubrics 跑多久/能否独占一卡/夜间错峰）。**harness 代码全部未在真服务验证**。
- 阻塞项（旧）: `git push` 3 个 commit 未推（见上）
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

### 2026-07-12 (Day 1)
- 开场：还 Q1（pin 版本，答半对：抓 soak 期，缺"对本项目致命=实验性接口升级即白测"+"代价"整块）；prefill/decode 边界焊死（(a)"KV prefill 算 decode 复用"对了、TTFT 恶化主因纠为**排队**非算力；(b) chunked prefill=限每 step 计算量、术语 prefill HoL blocking）。question-bank 新增"题目分层制度"（行号不背，记机制+war-story）
- workload 设计（用户主导，已定）：混合服务=简单问答短请求 + 长文档总结/长代码补全；**长 20 条 input 25000/output 512；短 100 条 input 512/output 256；burst 并发**。KV 账：587,040 tokens vs 预算 514,464 = **114% 超线→抢占预期成立**（注：output 从 256→512 曾把总量压到 89%，靠 15→20 长顶回超线）
- 重要纠偏（源码背书 scheduler.py v0.24.0）：**"被抢占的一定是短请求"错**。FCFS 抢占牺牲者=`running.pop()`=队尾=最晚到达者，长短无关；PRIORITY=最低优先级+最晚到达。短请求"受害"真机制=①新到→恰在队尾被抢②归一化惩罚更狠③排队/HoL。→ SJF 存在理由。源码事实：`num_computed_tokens=0`(recompute非swap)、`waiting.prepend`(塞回队头)、`num_preemptions`每请求自带（trace 直接抓）。KV 预算换算 514,464 = 70.65GiB ÷ 147,456B/token(2·36·8·128·2)
- 完成：harness 4 部件全写完——`workload.py`(混合生成，token-id精确长度+随机id防prefix cache confound+强制output长度) / `run_load.py`(async客户端,per-req TTFT/TPOT/e2e→CSV) / `metrics_poll.py`(/metrics时间序列) / `plot.py`(timeline+TTFT分层) / `run.sh`(一条命令编排,复用容器)
- **未完成/阻塞**：GPU 0/1 被 dzkduser evorubrics 各占 80GB → 起不了 8B 服务 → **harness 一行没在真服务验证**（4 个 API 假设待证：token-id prompt/min_tokens/ignore_eos/streaming）。用户选线下协调 GPU
- 数据：无（未跑）；代码 harness/*.py + run.sh
- 结论一句话：harness 脚手架就绪但未验证；今日真正卡点是共享 GPU 被占满，暴露"双卡独占"假设已不成立，需线下协调
- 待办：协调 GPU→冒烟验证 harness→A1 首个点；补推 3 个 commit

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
