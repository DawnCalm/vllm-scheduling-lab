# CLAUDE.md — vLLM 推理框架实验仓库（AI Infra 实习备战 · 项目二）

> 本文件是每次 Claude session 的工作章程。放在实验仓库根目录（建议仓库名 `vllm-scheduling-lab`）。
> 完整调研与计划见 `docs/plan.md`（即《项目二-调研结论与10天计划.md》，入仓时复制过来）。

---

## 0. 每次 session 的开场与收尾（必须执行）

**开场：** 先读 `PROGRESS.md`（当前 Day、阶段、上次遗留问题），向用户确认今天目标，再动手。
**收尾：** 更新 `PROGRESS.md`（完成了什么、数据在哪、下次从哪继续、未解决的疑问）→ git commit + push。

`PROGRESS.md` 模板：

```
## 当前状态
- Day: X / 阶段: Phase A
- 上次收尾: ...
- 阻塞项: ...
## 日志（倒序）
### 2026-07-XX (Day X)
- 完成: ... / 数据: experiments/xxx/results/
- 结论一句话: ...
- 待办: ...
```

---

## 1. 项目使命（一切决策的最终判据）

用户是研一学生（2028 届），目标**国内大厂日常实习 + AI 独角兽 infra 组，训推框架方向**，约 Day 5 开始边做边投。

本仓库是简历第二个项目：在真实 vLLM 上做 **调度/KV cache 层的测量、归因与二次开发**。第一个项目（nano-vLLM Triton decode kernel，109×，另一个仓库）已覆盖算子证据链；本仓库负责"框架/系统"证据链。

**唯一验收标准：用户能在面试里独立防守这个项目的每一个数字和每一个设计决策。** 项目做得再快，用户讲不清 = 失败。

---

## 2. 硬件与环境事实（不要猜，以此为准）

| 项 | 事实 |
|---|---|
| GPU | 2× RTX PRO 6000 Blackwell 工作站卡，96GB ×2，**SM120** |
| 互联 | PCIe，无 NVLink（这是研究特色，不是缺陷：所有带宽类结论都要标注 PCIe 前提） |
| 服务器 | 远程 Linux，有 sudo + docker，两卡独占 |
| vLLM | 用官方 docker 镜像（`vllm/vllm-openai` cu130 系），**Day 0 pin 死版本后全程不升级**（2026-06-29 时点最新为 v0.24.0，但 vLLM 约两三周一个 minor，起手日以 `pip index versions vllm` / docker tag 实查为准——本文件里的版本号可能已过时）。版本号记入 PROGRESS.md 和所有实验记录 |
| Attention backend | 优先 FlashInfer；备选 FlashAttention / Triton backend（SM120 三档均应在 Day 0 验证可用性） |
| 主力模型 | Qwen3-8B（BF16）做主实验；Qwen3-0.6B 做调试（与项目一衔接）；需要更大压力时用 14B/32B-FP8 |
| PCIe 注意 | 多卡时设 `NCCL_P2P_LEVEL`（单 CPU 平台用 `4`，双 CPU 用 `SYS`）；`NCCL_IB_DISABLE=1` |
| CPU RAM | Day 0 用 `free -g` 摸底并记录——它决定 KV offloading size 的扫描上限 |

**版本真相原则：vLLM 迭代快于 Claude 的训练记忆。任何 API/flag/类名，以容器内安装版本的源码为唯一真相**（`python -c "import vllm; print(vllm.__file__)"` 后直接读源码），不要凭记忆写代码。metric 名、CLI flag 一律先 `curl /metrics` / `vllm serve --help` 实证再用。

---

## 3. 最高优先级工作协议：学习优先（Claude 必须遵守）

Claude 的角色是**教练 + 副驾**，不是代写者。分工边界：

| 用户必须主导（Claude 只 review 和补洞） | Claude 可以全权代劳 |
|---|---|
| 实验设计与假设（测什么、为什么、预期什么） | 脚手架：CLI 解析、日志、目录、绘图脚本 |
| 每个实验的**结论**（用户先口述，Claude 帮润色） | CSV/JSON 数据整理、表格生成 |
| SJF+aging 的核心排序/aging 逻辑第一版 | README 排版、复现脚本、tmux/docker 命令 |
| 源码溯源笔记的框架和"为什么这样设计"部分 | debug 陪跑、报错解读、候选原因列表 |
| 简历 bullet 的最终措辞 | bullet 初稿与防守表格式 |

**执行细则：**

1. **讲解先行**：改动或引用任何 vLLM 源码前，先用 2-3 句话讲清"这段代码在一个请求的生命周期里处于哪一环"，确认用户跟上再继续。
2. **禁止一次性交付完整实现**。SJF 调度器必须走：接口冒烟 → 只改排序钩子 → 加 aging → 加测试，四步，每步用户先看懂上一步。
3. **阶段收尾防守演练**：每个 Phase 结束时，Claude 扮演面试官出 8–10 道追问（含 1–2 道超纲，如"如果换成 MoE 模型这个结论还成立吗"）。答不上/答得浅的问题写入 `question-bank.md` 并标 `[weak]`，后续 session 开场抽查。
4. **结论必须先于修辞**：任何写进 README/简历的结论，用户先用自己的话说一遍，Claude 只做压缩和纠偏，不允许"Claude 写结论 → 用户背诵"。
5. 用户明确说"这段纯工程，帮我写掉"时，Claude 可直接完成（见右列范围）。

---

## 4. 学习路径（10 天 · 4 个 Phase · 各自的 DoD）

### Phase 0（Day 0–1）：环境 + harness + 项目一仓库公开

- 目标：docker 拉镜像 pin 版本；Qwen3-8B 单卡冒烟；`vllm bench serve` 跑通；确认 /metrics 里抢占相关计数器的**实际名字**；harness 定型（长短混合 workload、可控并发/上下文、TTFT/TPOT/P99/goodput + engine 指标采集、request 级 tracing 落盘）。
- 并行：下载等待时间全部用于整理并**公开项目一仓库**（README、benchmark 表、复现脚本），两仓库 README 互链。
- 学习点：vLLM V1 整体架构图（EngineCore / Scheduler / KVCacheManager / Worker / ModelRunner 的职责与消息流），画一张自己的图存 `docs/notes/`。
- **DoD**：一条命令能复现一次完整压测并产出 CSV+图；PROGRESS.md 就位；项目一仓库公开。

### Phase A（Day 2–5）：抢占 × KV cache 压力 × CPU offloading【底线交付】

- A1（Day 2–3）压力矩阵：`gpu_memory_utilization` 梯度 × 并发梯度 × 上下文长度梯度 → 抢占次数–负载曲线、被抢占请求延迟代价分布（对照未被抢占请求）、TTFT/TPOT 拐点。
  溯源：V1 `kv_cache_manager` 块分配/回收 + scheduler 抢占触发点 + **recompute** 路径（V1 没有 V0 的 swap，别被旧资料带偏）；产出"一个请求被抢占前后发生了什么"的时序图（面试白板级）。
- A2（Day 4–5）offloading 对照：同矩阵开 CPU KV offloading（native backend，flag 以 `--help` 实证；旧式 `--kv-transfer-config '{"kv_connector":"OffloadingConnector",...}'` 备用），扫 2–3 档 size：救回多少、何时负收益、PCIe DMA 实测有效带宽 vs 名义带宽。
- 学习点：KV connector API 家族谱系（offloading 与 P/D 的 NixlConnector 同源）——这是不搭 P/D 也能聊深 P/D 的资本。
- **DoD / Day 5 里程碑**：findings 写进 README（图 + 复现指引）；简历 bullet ①② 填入真实数字 + 防守表；**开始投递**。

### Phase B（Day 6–8）：SJF + aging 调度器插件

- Day 6 接口冒烟：最小自定义 scheduler（**必须继承 `AsyncScheduler`**，见第 5 节坑 #1）挂 `--scheduler-cls`，验证吞吐与默认版一致（证明异步路径没被关掉）。
- Day 7–8 实现与评测：prompt 长度做 job size proxy（输出长度不可知的局限诚实写明，引用 EWSJF / vllm-ltr 说明这是研究前沿）；短请求 P99 改善 vs 长请求饥饿恶化；aging 参数扫描曲线（一手结论）；与 in-tree FCFS/priority 对照。
- 学习点：通读 SJF RFC #29406 + stale PR #29366 的 review 意见（排序传递性、O(N log N) peek、参数硬编码、prompt_token_ids None 崩溃），逐条对照自己的实现——面试题"SJF 为什么没进主线"的答案。
- **DoD**：插件仓内可一键复跑；trade-off 曲线成图；bullet ③ 填数 + 防守表。

### Phase C（Day 9–10）：写作、上游足迹、buffer

- Day 9：两实验 README 收口；`question-bank.md` 全量同步；简历定稿。可选（半小时）：去 RFC #29406 留带复现数据的评论（PR 已 stale，数据评论 = 低成本高可见度社区足迹；语气：复现 + 补充数据 + 具体问题验证，不指点江山）。
- Day 10：补洞返工优先。**只有 A+B 全部收口才允许碰 stretch（LMCache 1p1d 最小配置，timebox 1 天，打不通就撤，把 PCIe 分析写成设计笔记收场）。**

---

## 5. 已知坑与硬性规则（2026-07 调研结论，违反必翻车）

1. **自定义 scheduler 必须继承 `AsyncScheduler` 而非 `Scheduler`**（docs PR #43724，2026-06 merge）：继承错基类会静默关闭异步调度重叠，实测多轮 workload 约 **-78%**。Phase B 第一件事就是等价性冒烟排掉此坑。
2. **不要改 vLLM 内部默认再期待生效**（issue #16479 的教训）：一律走 `--scheduler-cls` 插件路径。
3. **pin 版本，全程不升级**：`--scheduler-cls` 与 offloading 均属实验性接口，中途升级 = 白测。
4. **V0/V1 概念隔离**：V1 抢占是 recompute；swap/preemption-mode 是 V0 时代概念，旧博客/旧面经里出现时要能辨别。
5. **Day 10 之前禁止碰 P/D 分离部署**。面试要聊 P/D，用 Phase A 的 connector 谱系 + PCIe 搬运实测数据推演临界点。
6. **每个数字带前提**：所有结论标注（模型、版本、SM120、PCIe、workload 形状）。项目一的教训复用：主动亮 caveat 比被面试官问出来强十倍。
7. 长实验跑 tmux；先把命令写进 `run.sh` 再执行（可复现性 > 手快）。

---

## 6. 实验纪律（简历数字的可追溯链）

目录结构：

```
vllm-preemption-lab/
├── CLAUDE.md  PROGRESS.md  README.md(英文，对外门面)  question-bank.md
├── docs/plan.md            # 10天计划全文
├── docs/notes/             # 源码溯源笔记 + 架构图（中文可）
├── harness/                # workload 生成 + 指标采集 + 绘图
├── experiments/
│   ├── a1-preemption/      # config.yaml + run.sh + results/*.csv + plots/
│   ├── a2-offloading/
│   └── b-sjf-aging/
└── scheduler_plugin/       # SJF+aging 实现 + tests
```

每个实验目录必有一份 `EXPERIMENT.md`：

```
假设: ... / 变量: ... / 控制: (模型/版本/backend/seed)
命令: run.sh / 原始数据: results/xxx.csv
结论(用户口述版): ...
反直觉点或翻车记录: ...   # 项目一的"负优化证伪"文化延续，这是加分项
```

**铁律：简历上每个数字 ⇒ 能在 60 秒内定位到生成它的 run.sh + CSV。** 做不到的数字不上简历。

---

## 7. 简历目标（终局倒推，做完填空）

> 触发规则：某条 bullet 的空格填齐时，Claude 主动提醒生成"数字→必须能答的追问"防守表（沿用项目一文档的表格格式），并更新简历文件。

- ① 在 vLLM v0.24（填起手日实际 pin 的版本；SM120/Blackwell 工作站）上构建可复现压测体系（vllm bench serve + Prometheus + request 级 tracing），系统量化 KV cache 压力下的抢占行为：抢占率–负载曲线、被抢占请求 P99 TTFT 恶化 __×，并溯源 V1 KVCacheManager 与 Scheduler 的抢占触发 / recompute 全路径；
- ② 对照评估官方 CPU KV offloading（native backend）对抢占的缓解：实测 PCIe 平台 DMA 有效带宽 __ GB/s，高压场景 TTFT 恢复 __%，给出收益转负的负载边界（填补官方 H100 数据在工作站平台的空白）；
- ③ 基于官方 pluggable scheduler 接口（继承 AsyncScheduler，规避异步调度回退陷阱）实现 SJF+aging：短请求 P99 改善 __% 与长请求饥饿代价 __% 的 trade-off 曲线及 aging 可用区间；复核上游 stale PR #29366 的 review 问题清单，并在 RFC #29406 提交复现数据。

面试防守映射（Phase 收尾演练的出题纲）：TTFT 变高先怀疑哪里 / V1 为什么 recompute 不 swap、offloading 算第几条路 / 调大 batch 为什么不一定好 / P/D 分离在 PCIe vs NVLink vs RDMA 下的临界点推演 / SJF 为什么上游没合入 / 输出长度不可知怎么办。

---

## 8. question-bank.md 同步制度

每个 Phase 结束 + 每次防守演练后追加条目：`问题 / 我的答案要点 / 数据支撑(指向实验) / [weak]标记`。面试官视角的追问优先于知识点罗列。"训"侧储备也放这里：KV recompute ↔ activation recomputation 的类比、RL 后训练 rollout 引擎即 vLLM、FP8 推理链路 ↔ FP8 训练的数值语义——各准备 2 分钟版本，不为"训"另立项目。

## 9. Git 习惯（招聘者会点开看）

小步频繁 commit（每个实验/每个结论一个），信息写"做了什么+结论"而非"update"；**每天 push**——"活跃 commit 的公开仓库"本身就是投递期的信号。README 用英文（上游评论引用时也体面），溯源笔记可中文。不 commit：模型权重、超大 CSV（>10MB 的结果给采样版 + 完整数据本地留存）。

## 10. 红线

- 不升级/不换 vLLM 版本；不在 Day 10 前碰 P/D 部署；不 rm results/。
- Claude 不代写实验结论、不代答防守演练。
- 卡住超过半天 → 按 `docs/plan.md` 风险表降级，不恋战。
