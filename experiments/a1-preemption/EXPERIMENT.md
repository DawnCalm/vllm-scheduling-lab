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

## 结论（用户口述版 · 跑完填）
【待填】

## 反直觉点 / 翻车记录
【待填 —— 项目一"负优化证伪"文化延续，抢占救回为负、拐点反常等都记这里】
