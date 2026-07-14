# question-bank

> 格式：`问题 / 我的答案要点 / 数据支撑(指向实验) / [weak]标记`
> 每个 Phase 收尾 + 每次防守演练后追加。[weak] 条目下次 session 开场抽查。

## 题目分层制度（2026-07-12 Day 1 确立）
面试**不会**问"某 socket 在哪一行"。行号的用途只有三个：①深度即保险（答第1层要流畅、能再下探一层）②少数题直接可问 ③war-story 弹药（被钩到才放）。
- **复习姿势**：记「机制 + 大致在哪个文件/哪一环」，**不背行号**。口述用"抢占触发在 KVCacheManager 块分配路径"，不用"line 420"。
- **真·高频直接可问（必须不虚）**：Q1、Q5、Q6、Q8、Q10。
- **机制级（知道机制即可，行号不背）**：Q2、Q3、Q4。
- **war-story（不主动抽查，被钩到才放）**：Q9（conda/flashinfer-jit-cache）、Q3 的 VLLM_ATTENTION_BACKEND 静默失效。

## Day 0 防守演练（2026-07-11 出题 + 当日作答批改）

1. [ok-半] 为什么 pin v0.24.0 而非当天最新 v0.25.0？代价是什么？
   → Day 1 补答：抓对 soak 期。缺两块——(1) 对**本项目**尤其致命：--scheduler-cls + offloading 是实验性接口，中途升级=前面测的全作废/不可复现（这才是"为什么是我"）；(2) **代价**没答（题目明确问了）：放弃 v0.25 新特性/bugfix、万一 v0.24 自身有坑也扛着、面试官反问"怎么知道不是已知 bug"→ 用"发布满 N 周 soak + 通读 release note"对冲。一句话防守版见 Day 1 批改。

2. [ok-优秀] 请求生命周期。用户答：ROUTER/DEALER 收请求、PUSH/PULL 回结果——**源码核对四个套接字全对**（core_client.py:521/556 ROUTER, engine/core.py:1090/1503 DEALER, :1608 PUSH, core_client.py:526/561 PULL）。补洞：漏了 Processor/OutputProcessor（在 API server 进程，非 EngineCore）；返回是**每 step** 产出 EngineCoreOutputs，不是每请求。

3. [weak] 怎么证明 backend 切换生效。用户反问"是不是测不同 kernel"——Day 0 目的是可用性验证。考点答案：认 cuda.py:420 日志签名 + VLLM_ATTENTION_BACKEND 静默失效坑。

4. [ok-浅] 自动选择机制。用户知道默认 FLASH_ATTN。机制补：显式→只 validate 那个否则 raise；未指定→get_valid_backends() 收集 validate_configuration 通过者，取 priority 最小者。

5. [ok-读错题] KV 换算。用户写 2*128*8*36*2=147,456 B/token（**公式正确**），但以为缺 seqlen/batch。纠：单位是 token，反用即可 514,464 = 70.65GiB ÷ 147,456。paged KV 是全局 token 预算。

6. [weak] chunked prefill。用户归因错为"KV block 放不下"。纠：是**每步计算量**调度（max_num_batched_tokens=每 step token 上限），目的是避免长 prefill 堵死其他 decode（prefill HoL blocking，官方 roadmap 项），非 KV 容量。

7. [weak-未知] concurrency 12.56x = 514,464÷40,960(max_model_len)。含义：满长请求最多同时装 12.56 个；KV 总需求越过 514,464 即触发抢占。是抢占水位线的刻画。

8. [weak-概念硬伤] TTFT/TPOT。用户说"TPOT 先恶化，因 decode 要算很多 KV cache"——**范畴错误**：算 KV=prefill→TTFT；decode 复用 KV 只算新 token。TPOT 涨因 decode batch 变大。通常 TTFT 先崩更狠（排队+抢占 requeue+recompute）。KV recompute 打进 decode 体感的唯一场景=抢占后 recompute（Phase A 靶心）。

9. [ok-糊] docker vs conda。用户答"版本对不上"太糊。精确根因：同版 vllm/torch，conda 缺 flashinfer-jit-cache 伴随包 → FlashInfer 走 JIT 误判 SM120<sm75。是"缺件走错代码路径"非"版本"。

10. [weak-过度自信] FP8 KV。用户说"很简单，三后端都受影响"。容量对（减半→~103万 token）。但**源码打脸**：FLASH_ATTN（SM120 默认）supported_kv_cache_dtypes=[auto,float16,bfloat16] **无 fp8**；FlashInfer 有 fp8/e4m3/e5m2/nvfp4；Triton 声明 fp8 但按算力 runtime 门控(triton_attn.py:471)。→ 开 FP8 会踢掉默认 backend 逼自动选择换 FlashInfer。串起 Q3/Q4。

**Day 0 总评**：概念地基扎实（ZMQ、KV 底层数字都有）。真问题集中在 prefill/decode 边界感（Q6/Q8/Q10 全栽在"KV 是 prefill 算的、decode 只复用"）——焊死这条线是 Phase A 溯源前提。

## Day 1 复查（2026-07-12）
- **(a) prefill/decode 边界**：✅ "KV prefill 算、decode 复用"焊死了。但 **TTFT 恶化的主因归错**——用户答"大量请求算 KV"（那是 prefill 算力争抢，次要）；主因是**排队**（请求卡 waiting 队列还没轮到 prefill）+ 抢占 requeue/recompute。记牢：**TTFT ≈ 排队 + prefill 时间，恶化先看排队不是先看算力**；TPOT 涨是独立机制=decode batch 变大。Q8 尾巴，不单标 weak。
- **(b) chunked prefill**：✅ 焊死。"限每 step 计算量、避免长 prefill 拖慢 decode"正确。术语标签：**prefill head-of-line blocking**，官方 roadmap 专治它。
- 结论：Q6/Q8/Q10 的病根（prefill/decode 边界）基本清除，Phase A 溯源前提达成。

## Phase B 预习（2026-07-12 Day 1 新学，架构图溯源时补）
11. [Phase B 必答·今日新学] 为什么自定义 scheduler 必须继承 `AsyncScheduler` 而非 `Scheduler`？
   → V1 默认**异步调度**：CPU 排第 N+1 步与 GPU 算第 N 步**重叠**，靠占位符实现。`AsyncScheduler` 只覆写两个钩子维护占位符：
   - `_update_after_schedule`（**打欠条**，async_scheduler.py:39）：decode token 还没从 worker 回来时，先 `num_output_placeholders += ...` 占位 → 排下一步用 `num_computed_tokens + placeholders` 预留 KV 块，不需知道 token 具体值。
   - `_update_request_with_output`（**还欠条**，:67）：真 token 回来 `num_output_placeholders -= len(new)`，结清。
   继承基类 `Scheduler` → 无这两覆写 → placeholders 恒 0 → 排不了下一步 → 同步停等 → **实测 -78% 吞吐（docs PR #43724），静默无报错**。
   → **Phase B 铁律**：①继承 AsyncScheduler 只覆写排序钩子（占位符内脏不碰，spec-decode/PP 分支是噪声）②Day 6 第一件事 = 等价性冒烟（排序不改，验证吞吐==默认版；掉 78% 就是继承错基类）。
   数据支撑：docs/notes/v1-architecture.md §3；待 Phase B 冒烟实测坐实 -78%。

## "训"侧储备（各准备 2 分钟版本）
- [ ] KV recompute ↔ activation recomputation 的类比
- [ ] RL 后训练 rollout 引擎即 vLLM
- [ ] FP8 推理链路 ↔ FP8 训练的数值语义

## Day 2 · A1 首个点防守演练（2026-07-14 · burst-20x100）
数据支撑：`experiments/a1-preemption/results/burst-20x100/`（requests.csv + metrics.csv + plots）

12. [weak·归因陷阱] 高压下短请求 TTFT 恶化，主因是"被抢占"还是"排队"？
   → **排队为主，抢占次要（只加剧 P99）**。数据：全程仅 13 次抢占 vs 100 条短请求，覆盖不了整片；短 TTFT 分位呈 ~28s/~67s **台阶**=分批 admission，非少数被抢；waiting 峰值 119 且 capacity 占 100%。**"排队≠抢占"**：waiting 里的请求从没进 running，谈不上被抢；抢占专指踢 running 队尾。→ 记牢：TTFT ≈ 排队 + 自身 prefill，先看能不能被 admit。

13. [weak·假象自曝] 短请求 TTFT(27.9s) 比长请求(18.6s) 差，是真机制还是 workload 假象？
   → **部分是发送顺序假象**。workload.py 先 add long 后 add short → 长请求 send_t 0.055–0.080s 全早于短请求 0.081–0.097s → burst+FCFS 先发先 admit。corr(send_t,ttft) 长0.70/短0.53。真机制部分=归一化惩罚不对称（固定等待砸小请求上占比灾难）。→ 下个点用 poisson 到达打散顺序复核。面试主动亮此 caveat。

14. [weak·概念区分] TPOT 两类接近(~90ms) 说明什么？
   → decode 是**同步 batch step**，running batch 每请求每次 forward 各进 1 token，共享同一 per-token 墙上时间 → TPOT 是 batch/step 级属性，**与请求类别无关**，跟输出长度无关。补：~90ms ≈ Day0 空载 ~12ms 的 7×（大 batch+高压+recompute 税，独立发现）。

15. [机制·已讲清] 为什么首次抢占滞后 KV 饱和 8s（37s 满→45s 才抢）？
   → KV=100% ≠ 立即抢占。抢占只在 running 请求要 append 新 token、申请新 block 而空闲=0 且不可 defer 时触发。block_size=16 → 每 16 token 才申请一次新块，8s = running 集合啃完最后 block 余量到首次分配失败的时间。引擎先从 waiting 灌满 KV，再等 running 长大到挤不出块才踢队尾。→ 待翻 scheduler.py 对着 `allocate_slots` 返回 None → `_preempt` 焊死。
