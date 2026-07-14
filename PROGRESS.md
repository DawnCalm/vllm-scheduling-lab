# PROGRESS

## ▶ 下次 SESSION 开场清单（Claude 读到这里就按①②③顺序执行，做完一项划掉一项）
1. **确认 GPU**：`nvidia-smi`。GPU 1 常驻师兄 RL rollout（TriLoRA ~21GB 低频）；正式实验固定 GPU 0。容器 `vllm-harness`（v0.24.0/Qwen3-8B）若还在且 healthy 可直接复用（run.sh 自动复用）。
2. **[weak] 抽查**：question-bank Q12–15（Day 2 A1 归因链）——重点让用户复述"排队为主/抢占加剧 P99 尾部"+"短请求受害=归一化惩罚+发送顺序假象"。答浅就重讲。
3. **A1 已收口**（首点 burst + poisson 复核 + 抢占率–负载曲线，bullet① 数字齐、结论焊死）。下一步二选一：
   - **(优先) Phase A2：CPU KV offloading 对照**（bullet②）——同压力矩阵开 offloading，扫 size，测 PCIe DMA 有效带宽 + TTFT 恢复% + 收益转负边界。flag 以 `vllm serve --help` 实证（native backend）。**run.sh 需加 server flag 透传**（当前只透传 workload 参数，offloading flag 要传到 docker run 的 server 侧）。
   - 或**补 A1 溯源**：Q15/Q18 的"申请块失败→_preempt"路径 + "长工作集撞预算边界"对着 scheduler.py `allocate_slots`/`_preempt` 焊死（per-request 抢占归因方案见 EXPERIMENT.md line 35）。
4. **溯源缺口**：Q15 的"申请块失败→`_preempt`"路径 + per-request 抢占归因方案（/metrics 只给聚合，见 EXPERIMENT.md line 35 三方案）。想深挖抢占时对着 scheduler.py 焊。

## 当前状态
- Day: 2 完成 / 阶段: **Phase A 进行中**（A1 首个点已成）
- 上次收尾: harness 在真服务验证通过（4 API 假设全过）+ 修 2 真 bug（死字段 gpu_cache_usage_perc、poller 信号泄漏挂死）；A1 首个点 burst-20x100 跑通并出结论；question-bank +Q12–15
- **阻塞项: 无**（GPU 已释放，两卡空闲）
- Git: 已同步（HEAD==origin/main 后再叠 Day2 三个 commit）；PROGRESS 旧注"3 commit 未推"已证实为**过时误记**（当时其实已 push）
- **Pin 版本: vLLM v0.24.0（docker `vllm/vllm-openai:v0.24.0`）——全程不升级**
- 运行中容器: `vllm-harness`（GPU0, Qwen3-8B, port 8000）——下次可复用或 `docker rm -f` 重起

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

### 2026-07-14 (Day 2) — GPU 到手，harness 验证 + A1 首个点
- **GPU 释放**：dzkduser evorubrics 撤离，两卡各 0 MiB。固定 GPU 0 跑。
- **harness 真服务验证**（Day 1 写完从没跑过）：起 v0.24.0/Qwen3-8B（~116s ready），手搓 curl 验 4 API 假设——①token-id 列表当 prompt ✅ ②min_tokens+ignore_eos 强制输出恰好 N（usage.completion_tokens 坐实）✅ ③streaming 抓 TTFT+include_usage ✅ ④/metrics 字段：3/5 在，**`gpu_cache_usage_perc` 不存在**（V0 旧名，V1 移除；kv_cache_usage_perc 是唯一真相）。
- **修 2 个真 bug（冒烟抓到）**：(1) 删死字段 gpu_cache_usage_perc（原会写空列）；(2) poller 经 `conda run` 起 → wrapper 不转发 SIGTERM → kill+wait 挂死 2min+孤儿进程 → 改 env python 直连（$! 是真 python，SIGTERM handler 干净 flush）。commit ccb09e4。
- **harness 增强**：抓 `num_requests_waiting_by_reason` 分列 capacity/deferred（capacity 排队 = KV 压力→抢占的因果信号）；timeline 加 capacity 线。
- **A1 首个点 burst-20x100**：120/120 ok，wall 76.6s。KV 峰 100%、waiting 峰 119@capacity 100%、首抢 @45.4s、13 次抢占。short TTFT 中位 27.9s/P99 67.7s、long 18.6/50.4；TPOT 两类 ~90ms。
- **结论（用户口述）**：短请求 TTFT 恶化**主因排队非抢占**，抢占 13× 仅加剧 P99 尾部；短请求受害更重=归一化惩罚 + **workload 先长后短的发送顺序假象**（corr(send_t,ttft) 长0.70/短0.53，诚实记为 caveat，下点用 poisson 复核）。TPOT 两类接近=decode 同步 batch step。commit 7ef8ec5。
- **纠偏（进 question-bank Q12–15 [weak]）**：用户初答把短请求慢归因"长抢短/被抢占"，纠为"排队为主"；TPOT 理由从"长输出少"纠为"batch step 级属性"。
- 数据：`experiments/a1-preemption/results/burst-20x100/`；结论 EXPERIMENT.md；反直觉/翻车 4 条已记。
- 结论一句话：harness 从"未验证"变"验证过+抓到 2 真 bug"；A1 首个点证实 114% 超线下 TTFT 恶化是 **capacity 排队主导**，抢占是尾部效应——SJF 的存在理由在数据上初现。
- **poisson 复核（同日续）**：受控三点 burst/poisson-r4/poisson-r12。**结论修正**：burst 里 short−long TTFT +9.4s **主体是发送顺序假象**（长先发），打散后（r12 同样饱和 KV100%/抢占14）塌到 **+0.8s**；归一化惩罚真实但次要（r12 short TTFT/e2e 0.34 vs long 0.22，小 e2e 分母放大）。意义：绝对延迟公平≠归一化公平，短请求归一化亏损=**SJF 要救的**（Phase B 动机落点）。附带教训：poisson 饱和阈值不能从 burst 排空速率线性外推（r4 rate=4 摊 33s 就没饱和，KV 仅 86%/0 抢占）。commit d4e7326；question-bank +Q16。
- **抢占率–负载曲线（同日续）**：固定 util 0.9、扫工作负载规模 57→148%、每点 3 重复（results/load-sweep/，聚合脚本 plot_sweep.py）。**核心结论**：①**P99 TTFT 单调随负载升、拐点 ~100% 预算线 = 真负载信号**；②**抢占非单调**（中位 0/0/1/12/0/1，峰在 114% 中等超载、重超载掉回 ~0），"preemption-vs-load"命名误导。机制（数据背书）：抢占峰在**长工作集≈预算**处（20 长=510k=99%），非总负载——114% waiting@sat≈0（全挤 running 贴天花板→抢占爆发）、148% waiting@sat≈111（长集 129% 装不下→摁进 waiting→churning running 小→少抢）。**顺序对照证伪**"长先发导致过度 admit"：打散顺序(interleaved rate=1000)仍抢中位 5≠0，抢占由稳态 packing 驱动、与顺序无关；顺序只动 TTFT 瞬态。方法学：burst 抢占计数高方差(114% 三次 4/12/22)，seed 不固定 asyncio 发射时序→需重复+误差带。commit 145f2f8；question-bank +Q17–20。
- 待办：**A1 已足够扎实（首点+poisson 复核+负载曲线，bullet① 数字齐）**。下一步 Phase A2 CPU KV offloading 对照（bullet②），或补 A1 溯源（Q15/Q18 的"申请块失败→_preempt" + 长工作集撞预算 对着 scheduler.py 焊）。

### 2026-07-12 (Day 1)
- 开场：还 Q1（pin 版本，答半对：抓 soak 期，缺"对本项目致命=实验性接口升级即白测"+"代价"整块）；prefill/decode 边界焊死（(a)"KV prefill 算 decode 复用"对了、TTFT 恶化主因纠为**排队**非算力；(b) chunked prefill=限每 step 计算量、术语 prefill HoL blocking）。question-bank 新增"题目分层制度"（行号不背，记机制+war-story）
- workload 设计（用户主导，已定）：混合服务=简单问答短请求 + 长文档总结/长代码补全；**长 20 条 input 25000/output 512；短 100 条 input 512/output 256；burst 并发**。KV 账：587,040 tokens vs 预算 514,464 = **114% 超线→抢占预期成立**（注：output 从 256→512 曾把总量压到 89%，靠 15→20 长顶回超线）
- 重要纠偏（源码背书 scheduler.py v0.24.0）：**"被抢占的一定是短请求"错**。FCFS 抢占牺牲者=`running.pop()`=队尾=最晚到达者，长短无关；PRIORITY=最低优先级+最晚到达。短请求"受害"真机制=①新到→恰在队尾被抢②归一化惩罚更狠③排队/HoL。→ SJF 存在理由。源码事实：`num_computed_tokens=0`(recompute非swap)、`waiting.prepend`(塞回队头)、`num_preemptions`每请求自带（trace 直接抓）。KV 预算换算 514,464 = 70.65GiB ÷ 147,456B/token(2·36·8·128·2)
- 完成：harness 4 部件全写完——`workload.py`(混合生成，token-id精确长度+随机id防prefix cache confound+强制output长度) / `run_load.py`(async客户端,per-req TTFT/TPOT/e2e→CSV) / `metrics_poll.py`(/metrics时间序列) / `plot.py`(timeline+TTFT分层) / `run.sh`(一条命令编排,复用容器)
- 完成（无 GPU 段）：**V1 架构图**（用户手画→批改→定稿，`docs/notes/v1-architecture.png`）+ **溯源笔记** `docs/notes/v1-architecture.md`（事实锚点 Claude 填、理解用户填，§3抢占路径/§4 KV账全焊死）。**AsyncScheduler 坑讲透**（打欠条/还欠条=异步重叠，继承错基类静默-78%）→ question-bank Q11（Phase B 必答）
- 学习修正：§4 曾把"70.65G 含权重激活"答反（应为扣掉后剩的），已纠；进程拆分主因=避 GIL 让 GPU 循环与 Python 逻辑隔离（非仅多副本）
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
