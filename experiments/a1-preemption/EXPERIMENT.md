# A1 — 抢占行为测量（压力矩阵）

> 状态：**设计已定，未跑**（GPU 被占，等释放）。假设先行——跑之前锁死，避免事后凑结论。

## 假设
1. 混合 workload 的**总 running token 数逼近 KV 预算（514,464 token）时，抢占开始出现**；越过后抢占次数随负载单调上升。
2. **被抢占的请求长短无关**（FCFS 牺牲者=running 队尾=最晚到达者）；但**短请求的归一化 TTFT 恶化最狠**（①新到→恰在队尾被抢 ②归一化惩罚不对称 ③长请求 HoL 排队）。
3. 存在 **TTFT/TPOT 拐点**：负载越过某点后 TTFT（先，主因排队+抢占 requeue）比 TPOT（后，decode batch 变大）更早、更陡地恶化。

## 变量（扫描维度 · Phase A 压力矩阵）
- `gpu_memory_utilization` 梯度（缩小 KV 预算 = 移动抢占水位线，核心旋钮）
- 并发梯度（长/短请求数量）
- 上下文长度梯度（长请求 input 长度）

## 控制（每次固定并记录）
- 模型：Qwen3-8B (BF16) · 版本：vLLM **v0.24.0** (docker `vllm/vllm-openai:v0.24.0`)
- backend：FLASH_ATTN（SM120 默认）· GPU：**GPU 0 独占**（若混跑注明背景负载）
- seed：workload seed 固定 · temperature=0（贪心，可复现）
- prefix caching：默认开——但 workload 用随机各异 token-id prompt，无前缀共享可利用（防它压低 KV 使用的 confound）
- output 长度：强制精确（ignore_eos + min_tokens==max_tokens），KV 轨迹可复现

## 代表性起手点（Day 1 设计，114% 超线）
- 长 20 条：input 25,000 / output 512 ；短 100 条：input 512 / output 256 ；burst 并发
- KV 账：587,040 token 需求 vs 514,464 预算 = **114% → 抢占预期成立**
- 命令：`harness/run.sh experiments/a1-preemption/results/burst-20x100 --n-long 20 --n-short 100`

## 溯源目标（跑完对照源码写）
- KVCacheManager 块分配/回收（`allocate_slots` 返回 None = 信号）
- Scheduler 抢占触发点 + 牺牲者选择（`running.pop()` / PRIORITY max）
- **recompute 路径**（`num_computed_tokens=0`；V1 无 swap）——"一个请求被抢占前后"时序图

## 命令 / 原始数据
- run.sh：见上（每个矩阵点一个 results 子目录）
- 原始数据：`results/<point>/requests.csv` + `metrics.csv` ；图 `results/<point>/plots/`
- ⚠️ per-request 抢占归因：`/metrics` 只给聚合计数；具体哪条被抢占待 Phase A 定方案（OTLP tracing / 解析 request 日志 / `num_preemptions` 字段暴露）

## 实测数字（首个点 burst-20x100 · 2026-07-14 · v0.24.0 / Qwen3-8B / SM120 / GPU0 / FLASH_ATTN）
原始数据：`results/burst-20x100/{requests,metrics}.csv`；图：`results/burst-20x100/plots/`

| 指标 | short (n=100) | long (n=20) |
|---|---|---|
| TTFT 中位 | **27.9s** | 18.6s |
| TTFT P99 | **67.7s** | 50.4s |
| TPOT 中位 | 91.7ms | 98.7ms |
| e2e 中位 | 51.3s | 69.0s |

引擎侧：KV 峰值 **100%**（>90% 占 144/321 采样点）；waiting 峰值 **119，capacity 占 100%**（deferred 恒 0）；
首次抢占 **@45.4s**（KV 饱和 ~37s 之后 8s）；累计抢占 **13 次**（集中 45–70s）；running 峰值 75；120/120 全成功；wall 76.6s。
对照基线：TPOT ~90ms ≈ Day 0 空载基线 ~12ms 的 **7×**（大 batch + 高压 + recompute 税）。

## 结论（用户口述版 · 2026-07-14）
114% 超线 burst 下，**短请求 TTFT 恶化的主因是 KV 容量排队**（capacity-waiting 峰值 119、占 waiting 100%），**抢占只是次要原因，仅加剧 P99**（全程 13 次，vs 100 条短请求，无法解释整片短请求都慢；短 TTFT 分位呈 ~28s/~67s 台阶 = 分批 admission 而非少数被抢）。**短请求受害更重**有两个原因：①归一化惩罚不对称（固定等待砸在小请求上占比灾难性）；②本次 workload 发送顺序先长后短，burst+FCFS 下长请求先被 admit。TPOT 两类接近（~90ms）证明 decode 是同步 batch step、per-token 墙上时间与请求类别无关。

## 复核：poisson 到达剥离顺序假象（2026-07-14 · 受控三点对比）
原始数据：`results/{burst-20x100, poisson-20x100-r4, poisson-20x100-r12}/`

| point | 到达/顺序 | KV峰 | 抢占 | short TTFT中位 | long TTFT中位 | short−long | short TTFT/e2e |
|---|---|---|---|---|---|---|---|
| burst-20x100 | 瞬时·长先发(混淆) | 100% | 13 | 27.9s | 18.5s | **+9.4s** | — |
| poisson-r4 | 公平·不饱和 | 86% | 0 | 0.3s | 0.3s | −0.0s | — |
| poisson-r12 | 公平·饱和 | 100% | 14 | 14.5s | 13.6s | **+0.8s** | 0.34 (vs long 0.22) |

**实验设计**：burst vs r12 都饱和(KV 100%)、抢占近似(13/14)，**唯一差别是到达顺序** → 隔离"顺序假象"。
r4 是意外发现的"健康 regime"锚点：**同样 120 请求，poisson 摊到 33s 窗口后引擎边到边排空、从不饱和**（rate 估算教训：burst 排空速率 1.6/s 不能线性外推到 poisson 饱和阈值；膝盖在 rate 4–8 之间）。

**修正结论（用户口述 · 权重重排）**：
- burst 里 short−long 的 **+9.4s 差，主体是发送顺序假象**（workload 先长后短→FCFS 先 admit 长）。打散顺序后（r12 同样饱和）绝对 TTFT 差**塌缩到 +0.8s**，两类趋同。
- **归一化惩罚真实但次要**：饱和排队下短请求 TTFT/e2e=0.34 vs 长 0.22——小 e2e 分母让同样的绝对排队延迟在归一化上抬升更多。触发条件是"饱和排队"大环境，非"被抢占"动作（14/100 短请求被抢，主体是排队等 admission；抢占只加剧 P99）。
- **意义**：绝对延迟公平 ≠ 归一化公平。短请求在 FCFS 下的归一化亏损 = **SJF 要救的东西**，此即 Phase B 的动机在 A1 数据上的落点。

## 反直觉点 / 翻车记录
- **假象自曝（诚实记录）**：短请求 TTFT(27.9s) 比长请求(18.6s) 更差，**部分是 workload 顺序假象**——20 长请求 send_t 0.055–0.080s、100 短请求 0.081–0.097s，长请求整体先发（workload.py 先 `add("long")`），burst+FCFS 下先发先 admit。`corr(send_t,ttft)` 长 0.70/短 0.53 佐证"后发→TTFT 高"。**下一个点用 poisson 到达（打散长短顺序）复核**，剥离顺序效应。
- **"排队 ≠ 抢占"易混**：waiting 里的 119 条从未进 running，谈不上被抢；抢占专指踢 running 队尾。短请求慢的主体是"从没被 admit"，不是"被抢"。
- **抢占滞后 KV 饱和 8s**：KV=100% ≠ 立即抢占；抢占只在 running 请求需 append 新 token、申请新 block 失败(空闲=0)时触发。block_size=16 → 每 16 token 才申请一次，8s = running 集合啃完最后 block 余量到首次分配失败的时间。
- **假设 2 修正**："被抢占长短无关"成立（FCFS=running 队尾）；但原假设把短请求受害主因押在"被抢占"，实测是**排队为主、抢占加剧尾部**——归因重心从抢占移到 capacity 排队。
