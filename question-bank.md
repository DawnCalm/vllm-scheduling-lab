# question-bank

> 格式：`问题 / 我的答案要点 / 数据支撑(指向实验) / [weak]标记`
> 每个 Phase 收尾 + 每次防守演练后追加。[weak] 条目下次 session 开场抽查。

## Day 0 防守演练（2026-07-11 出题 + 当日作答批改）

1. [weak-未答] 为什么 pin v0.24.0 而非当天最新 v0.25.0？代价是什么？
   → 用户漏答。Day 1 开场补。要点：soak 期 / 实验性接口(--scheduler-cls、offloading)中途升级=白测 / 可复现性 vs 新特性。

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

## "训"侧储备（各准备 2 分钟版本）
- [ ] KV recompute ↔ activation recomputation 的类比
- [ ] RL 后训练 rollout 引擎即 vLLM
- [ ] FP8 推理链路 ↔ FP8 训练的数值语义
