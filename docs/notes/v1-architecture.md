# vLLM V1 架构溯源笔记

> 版本锚定：v0.24.0（conda env `vllm` 同版源码可直读；docker 跑实验）。所有行号以此版为准。
> 图：见本目录 `v1-architecture.png`（Day 1 手画 → 批改 → 定稿）。
>
> **本笔记分工**：`【事实·已核实】`= Claude 从源码核对的客观锚点，可直接用；
> `【待你填】`= 你用自己的话写理解/为什么这样设计（章程：结论归你，不代写）。

---

## 0. 一句话总览
【待你填】用两句话说清 V1 是什么架构、和 V0 最大的不同是什么。
vLLM v1采用了EngineCore + AsyncLLM分层的架构，将请求管理、调度、模型执行都封装在了EngineCore中。v1和v0最大的不同就是**多进程 EngineCore + 统一调度器（默认 chunked prefill、异步重叠）**这套架构；
---

## 1. 两个进程 + 一座 ZMQ 桥（最容易画错的点）

**【事实·已核实】**
- API-server 进程（前台，可多副本）：`Entrypoint → AsyncLLM(async_llm.py) → Processor 分词(input_processor.py) → EngineCoreClient(core_client.py)`；回程 `OutputProcessor(output_processor.py) → Detokenizer(detokenizer.py) → HTTP SSE`。
- EngineCore 进程（后台，GPU 在此）：持有 `self.model_executor`(core.py:123) 和 `self.scheduler`(core.py:137)。
- ZMQ 桥（Day 0 已核对 4 套接字）：
  - 请求进：客户端 **DEALER → 服务端 ROUTER**
  - 结果出：引擎 **PUSH → 客户端 PULL**

**【待你填】**
- 为什么要把 EngineCore 拆成独立进程？（提示：GIL / 前台后台解耦 / 多 API server 副本） 
把 GPU 执行循环和 Python 的分词/detokenize/API 逻辑隔到不同进程，避免抢 GIL 拖慢 GPU 喂数。
- 为什么请求用 ROUTER/DEALER，结果用 PUSH/PULL？两种 ZMQ 模式语义差别是什么？
因为用户发出请求的时机是随机的，ROUTER/DEALER是一种异步的通信套接字，十分适合大模型推理这种场景，客户端只要发送请求就行，EngineCore可以异步接收请求。 PUSH/PULL也是异步的套接字，但是它们和前者的区别主要是它们是单向的，PUSH只能
发送，PULL只能接收。
---

## 2. step() 是引擎心跳（per-step，不是 per-request）

**【事实·已核实】** `core.py:479 def step()` 三步循环：
```
490  scheduler_output = self.scheduler.schedule(...)          # 谁能跑、各跑几个 token
491  future = self.model_executor.execute_model(scheduler_output)  # 丢 GPU 前向
504  engine_core_outputs = self.scheduler.update_from_output(...)  # 收结果、产 token
```
- 产出粒度：**每个 step 产出一批 EngineCoreOutputs**，不是每请求一次（Day 0 Q2 补洞）。

**【待你填】**
- 一个 step 里，prefill 请求和 decode 请求是怎么共处的？（联系 chunked prefill：max_num_batched_tokens 限每 step 计算量）
一个step中prefill和decode请求会组成mix batch一起送入model forward，如果prefill的token过多就会触发chunked prefill，一个请求分多个step()完成prefill，其中每个chunked的最大token数为prefill：max_num_batched_tokens。
- 为什么产出是 per-step 而非 per-request，对流式吐字意味着什么？
产出是per-step就可以慢慢吐，如果是per-request的话就会导致一次性包全部吐出来。
---

## 3. 抢占路径【Phase A 靶心 · 重点焊死】

**【事实·已核实】** 抢占是 **Scheduler 决策 + KVCacheManager 信号** 的分工，全在 `sched/scheduler.py`：
- `schedule()`(:388) 里为 running 请求要 KV 块：`allocate_slots()`(:525，调 `kv_cache_manager.py` → `block_pool.py`)。
- 要不到块 → 返回 `None`（= "KV 满了" 的**信号**，来自 KVCacheManager）。
- **踢谁由 Scheduler 决**：
  - 默认 FCFS：`preempted_req = self.running.pop()`(:562) = 队尾 = **最晚到达者**
  - PRIORITY：`max(running, key=(priority, arrival_time))`(:538) = 最低优先级 + 最晚到达
- 执行抢占 `_preempt_request()`(:1107)：
  - `num_computed_tokens = 0`(:1123) → **从头 recompute，不是 swap**（V1 无 swap）
  - `waiting.prepend_request()` → 塞回 waiting 队**头**，下步优先重排
  - `request.num_preemptions += 1` → 每请求自带被抢占计数（harness trace 直接抓此字段）

**【待你填 · 面试白板级】**
- 用自己的话讲"一个请求被抢占前后发生了什么"的时序（进 running → KV 满 → 被 pop → 释放块 → 回 waiting 队头 → recompute）。
比如正在running的请求，一个请求decode的时候发现，KV满了，就会告诉调度器，调度器就会踢掉队列末尾的请求，把它的KV cache释放出，这个被抢占的请求就会回到waiting队列的头部等待recompute。
- 为什么"被抢占的不一定是短请求"？短请求"受害"的三重真机制是什么？（①队尾②归一化惩罚③排队/HoL）
根据FCFS原则，被抢占的一定是后来的请求，后来的请求不一定就是短请求。 三重真机制：1.FCFS的调度下，短请求容易排在队列末尾 2. 短请求容易受到抢占影响，因为短请求需要计算和生成的token本来就不多，如果频繁抢占就会导致这个请求的性能损失严重 3. 队列前面的长请求会阻塞整个队列。
- 由此：自定义调度器(Phase B)该改哪个组件、不该碰哪个？为什么继承 `AsyncScheduler` 而非 `Scheduler`？
因此Phase B应该改Scheduler，设计SJF策略，让短请求优先被调度。 如果是Scheduler的话，就是同步调度，比如调度第N个请求，GPU去执行的时候CPU此时空转，同样当CPU进行调度的时候GPU也在空转，两者并不能overlap。同时AsyncScheduler因为有_update_after_schedule（打欠条）提前给还没生成的token进行占位，_update_request_with_output（还欠条）GPU算完了这时可以把前面打的欠条的token减掉，这样就能实现GPU计算和CPU调度的overlap。
---

## 4. KV cache 的账（数字要能现场推）

**【事实·已核实】** Qwen3-8B @ 默认 gpu_mem_util，v0.24.0：
- 每 token KV = `2(K/V) × 36(层) × 8(KV heads) × 128(head_dim) × 2(BF16 字节) = 147,456 B/token`
- KV 预算 70.65 GiB ÷ 147,456 B = **514,464 tokens**（"Maximum concurrency 12.56x" = 514,464 ÷ 40,960 max_model_len）
- 单位是 **token 不是请求**；paged KV 是全局 token 预算。

**【待你填】**
- 70.65 GiB 这个数是怎么被 vLLM 定出来的？（gpu_mem_util × 96GB − 权重 − 激活/CUDA graph）
70.65 G主要就是gpu_mem_util × 96GB-模型的权重-激活。
- 调低 gpu_mem_util 会怎样移动"抢占水位线"？（Phase A 核心旋钮）
gpu_mem_util低了能分配的KV Block也就少了，抢占水位线相应也就低了。
---

## 5. 组件职责速查（一句话锚点，细节读源码）

| 组件 | 文件 | 一句话职责 |
|---|---|---|
| AsyncLLM | engine/async_llm.py | API-server 侧引擎句柄，add_request 入口 |
| Processor | engine/input_processor.py | 分词，建 EngineCoreRequest |
| EngineCoreClient | engine/core_client.py | ZMQ 桥客户端（DEALER/PULL） |
| EngineCore | engine/core.py | busy loop，持 Scheduler+Executor，跑 step() |
| Scheduler | v1/core/sched/scheduler.py | 每 step 选请求/token；**抢占决策** |
| KVCacheManager | v1/core/kv_cache_manager.py | KV 块分配/回收；allocate 返回 None = 满 |
| BlockPool | v1/core/block_pool.py | 物理块池 |
| Executor→Worker→ModelRunner | executor/ , worker/gpu_worker.py , worker/gpu_model_runner.py | 真前向 |
| OutputProcessor / Detokenizer | engine/output_processor.py , detokenizer.py | token id → 文本，流式吐回 |

---

## 关联
- 请求生命周期 ZMQ 细节 → question-bank Q2
- prefill/decode 边界（KV prefill 算、decode 复用）→ question-bank Q8 + Day 1 复查
- 抢占牺牲者选择源码 → PROGRESS Day 1 日志
