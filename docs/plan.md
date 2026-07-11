# 项目二方向：调研结论与 10 天执行计划

> 调研日期：2026-07-11 ｜ 背景：研一升研二（2028 届），目标国内大厂日常实习 + AI 独角兽 infra 组，推理框架深挖路线；远程 Linux 服务器（sudo + docker），独占 2× RTX PRO 6000 Blackwell（96GB ×2，PCIe）；全职约 10 天，边做边投；真 vLLM 从零开始；项目一（nano-vLLM Triton kernel）代码尚未公开。

---

## 一、最终结论（TL;DR）

**主线 A（Day 2–5，底线交付）：抢占风暴 × KV cache 压力 × CPU offloading 三方对照研究。**
量化 KV 压力下的抢占行为对 TTFT/TPOT 的破坏 → 溯源 V1 KVCacheManager / Scheduler 的抢占触发与 recompute 路径 → 开启官方 CPU KV offloading（native backend）做对照，实测它救回多少、什么时候反而亏、PCIe 上 DMA 有效带宽是多少。

**主线 B（Day 6–8）：以官方 pluggable scheduler 接口实现 SJF + aging，并用同一套 harness 评测 trade-off。**

**P/D 分离（1P1D）降级为 stretch 选项**：仅当 A+B 提前完成才碰，timebox 1 天；PD 知识进面试知识储备，不作为简历项目。

**随手做**：SJF RFC #29406 的 PR 已被标 stale——带复现数据去评论是当前性价比最高的上游足迹机会。

三条核心理由：

1. **一次踩中官方 Q2 roadmap 两个工作项。** SIG Core 明确列了 "Address known scheduler issues (avoid excessive preemption, prefill HoL blocking)" 和 "Offloading: CPU offloading + Disk + overall connector API"。你之前调研只知道前者；把 offloading 对照加进来后，一个项目同时覆盖"调度 + KV cache 管理 + connector"三个 JD 关键词。
2. **面试考察方式明确偏向"测量 + 归因"而非"实现了多少功能"。** 圈内流传较广的 AI Infra 面试手册原话："不强调改过多少源码，而强调知道为什么这样设计、在什么 workload 下有效、会带来什么代价"；最高权重主题恰好是调度器角色、KV cache 动态管理、吞吐 vs 延迟权衡；高频追问"TTFT 变高先怀疑哪里"——主线 A 做完你手里就有这棵排查树的一手数据。
3. **官方 offloading 博客的所有数据都来自 H100 + 500GB DRAM 的服务器。** 工作站级 PCIe 平台上"offloading 何时划算"是公开数据空白，你的硬件劣势在这里再次变成研究价值（和项目一"比 FA 慢但能拆差距"是同一种叙事）。而且这些 PCIe KV 搬运数字可以直接迁移为 PD 分离面试题的弹药——不搭 PD 也能把 PD 聊深。

---

## 二、调研证据：你之前那轮调研的逐条核实

| 原说法 | 核实结果 |
|---|---|
| SIG Core Q2 把"避免过度抢占"列为工作项 | ✅ 属实。Q2 2026 roadmap（issue #39749）SIG Core 原文："Address known scheduler issues (avoid excessive preemption, prefill HoL blocking)"；同一节还有 "KV cache manager rethink" 和 "Offloading: CPU offloading + Disk + overall connector API" |
| SJF RFC #29406 | ✅ 存在。2025-11-25 由 Chen Jie 等人提出，NormalizedScorer / TimeAndLengthScorer / 堆队列设计。**新情报：配套 PR #29366 自 2026-02-02 起无更新，2026-06-26 被打 stale 标签**；hmellor 曾 approve 但核心 owner（WoosukKwon 等）未审。Review 中留有一串未确认解决的问题（排序传递性、O(N log N) peek、参数硬编码、prompt_token_ids 为 None 崩溃）——这份问题清单本身就是你的面试素材 |
| #16479：改 `_scheduler_default` 无效 | ✅ 属实。官方答复是实现自定义类 + `--scheduler_cls` 挂载，多数情况无需改 engine/worker |
| #43724 是"文档 issue"，说明要继承 AsyncScheduler | ⚠️ **修正：它是 docs PR，且已于 2026-06-11 merge。** 内容：`--scheduler-cls` 自定义调度器必须继承 `AsyncScheduler` 而非 `Scheduler`，否则关闭异步调度与 GPU 执行的重叠，实测多轮 workload 约 78% 性能回退。作者正是做 benchmark 时踩坑后提的 docs PR——这个先例说明"评测者提文档 PR 能被 merge" |
| V1 抢占以 recompute 为主 | ✅ 与官方 optimization 文档一致，实验按 recompute 机制设计 |
| P/D 分离是天花板选项但有环境风险 | ✅ 方向判断成立。官方文档仍标 experimental；NixlConnector 路线图（#33702，2026-02 开）非常活跃，UCX 默认传输 + CPU host buffer 路径可绕开 RDMA 网卡；LMCache 有现成 1p1d 教程。但从零起步的 10 天里塞不下"做得漂亮"的 PD——见第五节 |
| 时间预算假设"5 天核心实验已完成" | ⚠️ 实际完全没开始，所以原计划里"+1~2 天抢占研究"必须重排为本 10 天的主体 |

**调研新增的关键情报（你之前对话里没有的）：**

1. **CPU KV offloading connector 已官方化并高速迭代。** 官方博客（2026-01-08）：native backend（`--kv-offloading-backend native --kv-offloading-size <GB>`），DMA 异步搬运，v0.12 起块粒度 0.5–2MB 大幅提升 DMA 效率；单请求 TTFT 提升 2–22×、并发吞吐最高 9×（H100 数据）。近期 release notes 进一步出现 "General CPU KV cache offloading mechanism for V1, with pluggable cache policy and **block-level preemption handling**"——官方正在把 offloading 和抢占处理直接挂钩，这正是主线 A 的时效性所在。
2. **当前版本线：** GitHub 最新 release v0.24.0（2026-06-29）。注意 vLLM 现在约两三周一个 minor 版本（v0.22.1 是 6 月 5 日），本文档里的版本号写下即开始过期——起手那天以服务器上 `pip index versions vllm` / 官方 releases 实查为准，然后 pin 死不动。
3. **SM120（你的卡）已是官方支持路径。** 近期 release 明确含 SM120 优化 kernel；社区有专门的 RTX PRO 6000 运行指南：推荐 docker `vllm/vllm-openai` cu130 系镜像、FlashInfer 为主力 attention backend、FP8 KV cache 可用；PCIe 平台注意 `NCCL_P2P_LEVEL` 设置。你跑 Qwen3 系 dense 小中模型基本无雷（雷区集中在 NVFP4 MoE / MLA 大模型，与你无关）。
4. **面试/JD 信号。** DeepSeek 2026 招聘：加分项原文"开源框架（Megatron-LM、vLLM、DeepEP）**深度二次开发**"，职责含 KV Cache、长上下文推理——你两个项目合起来正好命中"vLLM 深度二次开发"。字节 Seed 实习 JD 写的是宽泛的"分布式训练、高性能推理、模型压缩与部署"。结论：JD 层面不逐词考关键词，筛选与面试真正区分人的是 smarter.xin 手册说的第三层——"知道哪些是 vLLM 特有、哪些是推理系统共性，自己设计时知道走哪条路"。
5. **学术竞品定位确认。** EWSJF（arXiv 2601.21758，2026-01）与 vllm-ltr（NeurIPS'24）占研究新颖性赛道；你定位"实现 + 评测 + 讲清 trade-off"，笔记里大方引用即可，不竞速。

---

## 三、10 天执行计划

> 原则：每一天有明确交付物；任何环境类问题卡住超过半天，走风险表降级路径；Day 5 是"可投递里程碑"。

**Day 0（0.5–1 天）｜环境 + 项目一仓库启动**
- 服务器上 docker 拉官方镜像（pin 当天最新稳定版，2026-06-29 时点为 v0.24.0，以当天实查为准），Qwen3-8B 单卡冒烟；确认 attention backend（优先 FlashInfer）与 `vllm bench serve` 跑通。
- 确认 Prometheus 指标暴露，找到抢占相关计数器（V1 metrics 设计文档里有）；`free -g` 摸底 CPU RAM（决定 offloading size 上限）。
- 镜像/权重下载的等待时间全部用来整理项目一仓库（README、benchmark 数据表、复现脚本）——公开它是 Day 1 的交付物之一。

**Day 1｜harness 定型 + 项目一仓库公开**
- workload 生成器：长短混合、可控并发、可控上下文长度（复用你 nano-vLLM 的 benchmark 方法论：warmup、中位数、双层对照矩阵）。
- 采集脚本：TTFT / TPOT / P99 / goodput + engine 侧指标（抢占计数、cache 使用率），request 级 tracing 落盘。
- 新开 repo（如 `vllm-scheduling-lab`），与 nano-vLLM 仓库 README 互链。

**Day 2–3｜实验 A1：抢占风暴量化 + 机制溯源**
- 压力矩阵：`gpu_memory_utilization` 梯度 × 并发梯度 × 上下文长度梯度 → 抢占次数–负载曲线、被抢占请求的延迟代价分布（对照未被抢占请求）、TTFT/TPOT 拐点。
- 溯源笔记：V1 `KVCacheManager` 块分配/回收 + Scheduler 抢占触发点 + recompute 路径，画一张"一个请求被抢占前后发生了什么"的时序图（面试可白板复述）。

**Day 4–5｜实验 A2：offloading 对照 + 可投递里程碑**
- 同一压力矩阵开 `--kv-offloading-backend native`，扫 2–3 档 offloading size：救回多少 TTFT/吞吐、什么负载下为负收益、PCIe DMA 实测有效带宽 vs 名义带宽。
- **里程碑：** repo 推 findings + 图表 + 复现指引；项目二简历 bullets 初稿（模板见第六节）填入真实数字；**开始投递**。

**Day 6｜实验 B 接口验证（先踩坑再写逻辑）**
- 最小自定义 scheduler（继承 `AsyncScheduler`，仅改队列排序钩子）挂 `--scheduler-cls`，跑行为等价性冒烟：吞吐与默认版一致 → 证明没踩 #43724 那个 78% 回退的坑。

**Day 7–8｜实验 B：SJF + aging 实现与评测**
- 启发式：prompt 长度做 job size proxy（输出长度不可知的问题诚实写进局限，并引用 EWSJF / vllm-ltr 说明这正是研究前沿）。
- 评测：短请求 P99 改善 vs 长请求饥饿恶化、aging 参数扫描曲线（这条曲线大概率是你自己的一手结论）；与 in-tree FCFS / priority 策略对照。

**Day 9｜写作日**
- 两个实验的 README / 图表 / 复现指引收口；同步 `question-bank.md`；简历 bullets 定稿。
- （可选，半小时）去 RFC #29406 留带复现数据的评论：PR 已 stale 四个多月，一条"我在 v0.22 + SM120 上复现了 SJF 收益，数据如下，另外 review 中提到的排序传递性问题我验证了 X"的评论，是低成本高可见度的社区足迹。

**Day 10｜buffer**
- 补洞返工优先；若 A+B 均已收口，才按第五节 timebox 规则尝试 stretch C（LMCache 1p1d）。

---

## 四、风险表与降级路径

| 风险 | 概率 | 预案 |
|---|---|---|
| SM120 上某 backend 精度/可用性问题 | 低 | 用官方 docker 镜像；FlashInfer ↔ FlashAttention ↔ Triton backend 三档切换；参考社区 RTX PRO 6000 指南的 env vars |
| offloading flag 随版本变动 | 中 | pin tag；旧式 `--kv-transfer-config '{"kv_connector":"OffloadingConnector",...}'` 做备用写法 |
| scheduler-cls 接口实验性变更 | 中 | pin tag；Day 6 等价性冒烟先行；接口对不上就退回改源码 fork（同样能讲，只是少了"插件化"卖点） |
| CPU RAM 不足限制 offloading | 低 | Day 0 摸底；用小 size 梯度也足以画出趋势线 |
| 时间超支 | 中 | **A 是底线交付**（单独成立）；B 可缩为"实现 + 单组对照"；C 直接砍 |
| 服务器临时不可用 | 低 | 所有实验脚本化 + 结果落盘，随时可断点续跑 |

---

## 五、为什么 P/D 分离这次不做成项目

不是方向不好——恰恰因为它太热才要冷静：官方文档仍标 experimental，connector 搭建摩擦（proxy/router、NIXL 配置、版本匹配）是三个方向里唯一可能吞掉你 2–3 天还没有产出的。从零起步的 10 天里，一个做塌的 PD 不如两个做实的 A+B。

但你不会在面试里吃亏，因为主线 A 给了你三样 PD 弹药：offloading 与 PD 的 NixlConnector 同属 KV connector API 家族（同一个 SIG Core roadmap 条目管辖）；你实测过 PCIe 上 KV 搬运的真实带宽和开销占比，可以现场推演"PD 在 PCIe / NVLink / RDMA 下的临界请求长度"；NixlConnector 路线图 #33702 你通读过（UCX 默认、CPU host buffer、异构 TP 已支持、FP8 KV cache 在计划中）。这套组合拳在面试里的效果，不弱于"我照教程搭过 1P1D"。

如果 Day 10 之前 A+B 全部收口：LMCache 官方 1p1d NIXL 教程起步，timebox 一天，目标只定"打通 + 一组 colocated vs disaggregated 对照"；打不通就把已有的 PCIe 分析写成设计笔记收场，不恋战。

---

## 六、简历 bullets 草稿（项目二，做完填数）

延续项目一"数字可防守 + 主动亮 caveat"的风格：

- 在 vLLM v0.24（填起手日实际 pin 的版本；SM120/Blackwell 工作站平台）上构建可复现压测体系（vllm bench serve + Prometheus + request 级 tracing），系统量化 KV cache 压力下的抢占行为：抢占率–负载曲线、被抢占请求 P99 TTFT 恶化 __×，并溯源 V1 KVCacheManager 与 Scheduler 的抢占触发/recompute 全路径；
- 对照评估官方 CPU KV offloading（native backend）对抢占的缓解效果：实测 PCIe 平台 DMA 有效带宽 __ GB/s，offloading 使高压场景 TTFT 恢复 __%，并给出收益转负的负载边界（填补官方 H100 数据在工作站平台的空白）；
- 基于官方 pluggable scheduler 接口（继承 AsyncScheduler，规避异步调度回退陷阱）实现 SJF+aging 调度策略：短请求 P99 改善 __% 与长请求饥饿代价 __% 的 trade-off 曲线，aging 参数扫描给出可用区间；复核上游 stale PR #29366 的 review 问题清单并在 RFC #29406 提交复现数据。

## 七、面试防守映射（对齐你项目一文档的表格风格）

| 追问 | 你的弹药 |
|---|---|
| TTFT 变高先怀疑哪里？ | 自测排查树：排队/HoL → 抢占 → prefill 干扰 → cache miss，每一层有自己的曲线 |
| V1 为什么用 recompute 不用 swap？ | 溯源笔记 + "官方后来补的第三条路正是 CPU offloading，我测过它什么时候值" |
| 调大 batch 为什么不一定更好？ | 你的抢占–负载曲线就是标准答案的一手版本 |
| PD 分离了解吗？ | connector 家族谱系 + 自测 PCIe KV 搬运成本 + 推演不同互联下的分离临界点 |
| SJF 为什么上游没合入？ | stale PR 的 review 问题清单（排序传递性、O(N log N) peek、参数硬编码）你逐条复核过 |
| 输出长度不可知怎么办？ | 诚实讲 prompt-length proxy 的局限，引 EWSJF/vllm-ltr 说明前沿方案 |

## 八、关于"训"的半页话

日常实习面试里"训"不需要第三个项目撑：概念迁移讲清楚就够——KV recompute 与训练侧 activation recomputation 是同一类"算力换显存"权衡；RL 后训练的 rollout 引擎就是 vLLM（roadmap 有专门 RL SIG），你对调度/KV 的理解直接适用于"rollout 为什么慢"这类问题；你项目一的 FP8 W8A8 链路与训练侧 FP8 是同一套 scaling/数值语义。这些放进 question-bank 里各准备一段两分钟版本即可。

---

## 附：本文关键信源

- vLLM Q2 2026 Roadmap（SIG Core 原文）: https://github.com/vllm-project/vllm/issues/39749
- SJF RFC: https://github.com/vllm-project/vllm/issues/29406 ｜ stale PR: https://github.com/vllm-project/vllm/pull/29366
- 自定义调度器正确姿势: https://github.com/vllm-project/vllm/issues/16479 ｜ AsyncScheduler 文档 PR（2026-06-11 merged）: https://github.com/vllm-project/vllm/pull/43724
- CPU KV offloading 官方博客（2026-01-08）: https://vllm.ai/blog/2026-01-08-kv-offloading-connector
- P/D 分离文档（experimental）: https://docs.vllm.ai/en/stable/features/disagg_prefill/ ｜ NixlConnector 路线图: https://github.com/vllm-project/vllm/issues/33702 ｜ LMCache 1p1d 教程: https://docs.lmcache.ai/disaggregated_prefill/nixl/1p1d.html
- RTX PRO 6000 / SM120 社区运行指南: https://github.com/local-inference-lab/rtx6kpro/blob/master/inference-engines/vllm.md
- benchmark CLI: https://docs.vllm.ai/en/latest/cli/bench/serve/ ｜ V1 metrics 设计: https://vllm.hyper.ai/docs/design-v1/metrics/
- 面试深度标准: https://smarter.xin/posts/cc221b1e/
- DeepSeek 2026 招聘信息: https://www.0rg.cn/web/2026-06-27-deepseek-job.html ｜ 字节 Seed 实习: https://www.wondercv.com/xiaozhao/bytedance-seed-2027-llm-6185-235c13/
- EWSJF: https://arxiv.org/html/2601.21758v1 ｜ vllm-ltr: https://haoailab.com/blogs/vllm-ltr/
