# question-bank

> 格式：`问题 / 我的答案要点 / 数据支撑(指向实验) / [weak]标记`
> 每个 Phase 收尾 + 每次防守演练后追加。[weak] 条目下次 session 开场抽查。

## Day 0 防守演练（2026-07-11 出题，用户未作答 → 全部先标 [pending]，Day 1 开场作答）

1. [pending] 你为什么 pin v0.24.0 而不是起手当天最新的 v0.25.0？pin 版本的代价是什么？
2. [pending] V1 里一个请求从 HTTP 进来到第一个 token 返回，完整链路是什么？（注意：启动时构建 vs 每请求执行要分清；返回路径别漏）
3. [pending] 你的实验怎么**证明** attention backend 真的切换了？如果面试官追问"环境变量设了没生效你怎么发现的"？
4. [pending] SM120 上 v0.24.0 默认选了哪个 backend？vLLM 的 backend 自动选择机制大致怎么工作（优先级、validate_configuration）？
5. [pending] 启动日志说 KV cache 70.65 GiB = 514,464 tokens——从模型结构（Qwen3-8B: 36 层、GQA 8 KV头、head_dim 128、BF16）推导一下这个换算，对不对得上？
6. [pending] chunked prefill 是什么？max_num_batched_tokens=8192 这个默认值意味着什么 trade-off？
7. [pending] 日志行 "Maximum concurrency for 40,960 tokens per request: 12.56x" 是什么意思？它和抢占风险什么关系？
8. [pending] 基线 TTFT 190ms / TPOT 12.4ms：TTFT 和 TPOT 分别主要由什么决定？并发加大时哪个先恶化、为什么？
9. [pending] 同一份 vllm 0.24.0，docker 里能跑、conda env 里崩（sm75 误报），说说你的排查过程和根因。
10. [pending]（超纲）如果开 FP8 KV cache，514K tokens 会变成多少？对三个 backend 的可用性有影响吗？（Day 0 没验，答思路即可）

## "训"侧储备（各准备 2 分钟版本）
- [ ] KV recompute ↔ activation recomputation 的类比
- [ ] RL 后训练 rollout 引擎即 vLLM
- [ ] FP8 推理链路 ↔ FP8 训练的数值语义
