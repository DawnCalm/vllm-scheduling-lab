# PROGRESS

## 当前状态
- Day: 0 / 阶段: Phase 0（环境 + harness + 项目一仓库公开）
- 上次收尾: 无（今天起手）
- 阻塞项: 无
- **Pin 版本: vLLM v0.24.0（docker `vllm/vllm-openai:v0.24.0`，2026-06-29 发布，2026-07-11 起手日选定）——全程不升级**

## 环境事实（2026-07-11 实测）
- GPU: 2× RTX PRO 6000 Blackwell **Server Edition**, 96GB ×2, SM120, driver 580.119.02, PCIe 无 NVLink
- CPU RAM: 125 GB 总量 / ~108 GB 可用 → KV offloading size 扫描上限约 60–80 GB
- 磁盘: 起手时仅剩 66 GB（85% 已用）⚠️ 14B/32B 权重暂不下载；大 CSV 注意采样
- 网络: huggingface.co 直连可用（~1.1s）
- 镜像 tag 实况: v0.24.0 只有默认版与 cu129 变体（调研文档中"cu130 系"已过时），pin 默认 tag
- 本机另有 conda env `vllm`（0.23.0），仅作应急备用，实验一律走 docker

## 日志（倒序）

### 2026-07-11 (Day 0)
- 完成: 环境摸底（GPU/RAM/磁盘/网络）；版本实查并 pin v0.24.0（当日 v0.25.0 刚发布零 soak，弃）；git init + 目录骨架；docker 镜像与 Qwen3-0.6B/8B 权重后台下载中
- 数据: 无（今日为环境日）
- 结论一句话: 待补
- 待办: Qwen3-8B 单卡冒烟 / attention backend 三档验证 / vllm bench serve 跑通 / curl /metrics 找抢占计数器实名 / 项目一仓库整理（用户）
