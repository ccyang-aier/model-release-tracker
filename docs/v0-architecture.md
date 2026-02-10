# Model Release Tracker（v0）架构设计说明

## 1. 背景与目标

本项目用于实现一个“模型新版本发布自动化哨兵”，以轮询方式持续监控多个社区/平台的更新动态（如 vLLM、SGLang、HuggingFace、魔塔等），当检测到与指定模型/组织相关的更新（如 DeepSeek、Qwen 等，可配置）时，通过多种通知渠道发出告警（如 WeLink 群机器人、邮件等）。

v0 版本的核心目标：

- 多平台轮询抓取：周期性抓取目标页面/接口的最新变更
- 统一事件模型：将不同平台的更新归一为统一事件结构
- 规则匹配与告警：按可配置规则判断是否需要告警并发送通知
- 幂等与断点续跑：避免重复告警，进程重启后可以延续进度

## 2. 监控目标（当前整理）

以下 URL 为当前明确的监控目标（v0 将以“可配置 source + 可扩展适配器”的方式纳入）：

### 2.1 GitHub（vLLM / SGLang）

- vLLM Pull Requests：https://github.com/vllm-project/vllm/pulls
- vLLM Issues：https://github.com/vllm-project/vllm/issues
- SGLang Issues：https://github.com/sgl-project/sglang/issues
- SGLang Pull Requests：https://github.com/sgl-project/sglang/pulls

说明：

- v0 实现不建议直接“爬网页 HTML”，优先使用 GitHub API（Issues/PR/Search/Events），上述 URL 作为“监控对象定义”，最终由 GitHub 适配器转为 API 拉取。
- 告警规则可以围绕标题、正文、标签、作者、变更链接等字段进行匹配（例如关键词 DeepSeek/Qwen）。

### 2.2 HuggingFace（DeepSeek 组织）

- DeepSeek models：https://huggingface.co/deepseek-ai/models
- DeepSeek models（分页）：https://huggingface.co/deepseek-ai/models?p=1

说明：

- v0 优先通过 HuggingFace Hub 的能力（API 或页面可解析信息）获取模型列表及更新时间等信号。
- 需要处理分页与新增模型/模型卡更新等场景，最终归一成统一事件。

### 2.3 魔塔 ModelScope（DeepSeek 组织）

- DeepSeek organization models：https://modelscope.cn/organization/deepseek-ai?tab=model

说明：

- v0 先以“组织模型列表变化/模型更新时间变化”为主要信号，后续可逐步丰富为版本发布、commit 等更细粒度事件。

## 3. 范围与非目标

### 3.1 v0 范围

- 轮询式监控（daemon 或定时任务均可）
- 基于配置的“监控目标 + 规则 + 通知渠道”
- 支持至少 1 个通知渠道（建议 WeLink）与 1 个落地存储（建议 SQLite）
- 支持至少 1 个 source（建议 GitHub：PR/Issue）

### 3.2 v0 非目标（可在 v1+ 演进）

- 实时 webhook 推送（如 GitHub webhook）
- 完整的告警重试队列与补偿机制（v0 先做到“失败记录 + 下周期继续”）
- 可视化管理后台
- 分布式部署与横向扩展（v0 默认单机即可）

## 4. 总体架构

将系统按职责拆分为 5 层，保证“新增平台/新增通知方式”时对核心流程影响最小：

1. Source（平台适配层）：每个平台一个适配器，负责拉取、解析、计算游标
2. Normalize（统一事件层）：将平台差异归一为统一事件模型
3. Rules（规则匹配层）：对统一事件进行匹配，确定是否需要告警及原因
4. State（状态与幂等层）：维护游标与已处理事件集合，保证断点续跑与去重
5. Notify（通知层）：多渠道通知，统一消息格式

数据流概览：

Source.poll(cursor) -> events[] + new_cursor
events[] -> normalize -> rules.match -> state.dedupe -> notify.send -> state.persist

## 5. 模块设计

### 5.1 Source（平台采集）

职责：

- 从平台拉取“自 cursor 以来的增量变化”
- 解析为平台事件，映射为统一事件结构
- 输出新的 cursor

建议提供统一接口：

- poll(cursor) -> (events, new_cursor)

Source 关键设计点：

- 每个 source 都有唯一 key（例如 github:vllm-project/vllm:issues）
- 每个 source 都维护独立 cursor（避免不同资源互相影响）
- 内部实现需要考虑限流（429）、鉴权（token）、超时与重试

### 5.2 Normalize（统一事件）

将不同平台的更新统一为 ReleaseEvent（或更通用的 TrackerEvent）：

- 避免后续规则/通知层依赖平台字段
- 统一去重与存储模型

### 5.3 Rules（规则匹配）

输入：统一事件
输出：是否命中 + 命中原因（可多条）

v0 规则建议（最小可用）：

- keyword：对 title/summary/body 等字段做大小写不敏感匹配
- source filter：允许只监控某些平台/某些资源（如只看 vLLM 的 PR/Issue）

### 5.4 State（幂等与断点续跑）

v0 推荐使用 SQLite 作为 state store，原因：

- 单机可靠、事务保证一致性
- 同时解决 cursor 持久化与事件去重集合

建议至少持久化两类信息：

- cursor：每个 source 的最新游标
- seen_events：事件指纹集合（或 alert 记录表），用于去重

### 5.5 Notify（通知）

抽象统一 Notifier 接口：

- send(alert) -> success/failure

v0 至少落地 1 种通知方式：

- WeLink webhook：向群机器人发送文本/富文本消息

可选扩展：

- Email（SMTP）

## 6. 目录结构（建议 v0 版本）

v0 建议以 Python 包组织，保持清晰边界（新增平台只加文件，不改核心 runner）：

```
model-release-tracker/
  README.md

  docs/
    v0-architecture.md

  src/mrt/
    main.py
    config.py
    models.py
    runner.py

    sources/
      base.py
      github.py
      huggingface.py
      modelscope.py

    rules/
      matcher.py

    state/
      store.py
      sqlite_store.py

    notify/
      base.py
      welink.py
      email.py
      formatter.py

  tests/
    test_rules.py
    test_dedupe.py
    test_sources_github.py
```

说明：

- v0 可以先落地 github + sqlite + welink，huggingface/modelscope 适配器先占位，逐步补齐。
- 目录命名与拆分的目标是：每个模块职责单一，尽量不出现“核心流程和平台细节混在一起”的文件。

## 7. 核心数据结构（建议）

### 7.1 统一事件：TrackerEvent

用于承载“任何平台、任何资源类型”的变化：

- source：平台标识（github/huggingface/modelscope）
- resource_type：资源类型（repo_issue/repo_pr/model_list/model 等）
- resource_id：资源唯一标识（如 vllm-project/vllm 或 deepseek-ai）
- event_type：事件类型（issue_opened/pr_opened/pr_merged/model_added/model_updated 等）
- event_id：平台侧唯一 id（若缺失则用稳定组合生成）
- title：标题（issue/pr 标题、模型名等）
- summary：摘要（正文截断、变更说明等）
- url：跳转链接（用于通知）
- occurred_at：事件发生时间（若平台给出）
- observed_at：本系统观察到的时间（本地生成）
- raw：原始字段（可选，用于排障与后续增强）

### 7.2 告警：Alert

- fingerprint：事件指纹（用于幂等）
- matched_rules：命中规则列表（例如 keyword:deepseek）
- channels：需要发送的渠道（welink/email）
- content：通知内容（由 formatter 生成）
- created_at：告警创建时间

### 7.3 事件指纹（fingerprint）

用于去重，建议由以下稳定字段组合后 hash：

- source + resource_type + resource_id + event_type + event_id

当平台缺少 event_id 时，使用可重建字段组合生成稳定 id（例如 url、标题、occurred_at 等）。

## 8. 端到端执行流（详细）

### 8.1 启动阶段

1. 加载配置（sources、规则、通知渠道、轮询间隔、密钥引用等）
2. 初始化 StateStore（连接 SQLite，确保表存在）
3. 构建 Source 实例列表（每个 source 拿到自己需要的配置，例如 repo 列表）
4. 构建 RuleMatcher（预编译关键词/正则）
5. 构建 Notifier 列表（WeLink/Email）

### 8.2 一次轮询周期（poll cycle）

对每个 source（可并发、需要限流）：

1. 从 StateStore 读取该 source 的 cursor
2. 调用 source.poll(cursor) 获取 events 与 new_cursor
3. 对每个 event：
   1) 生成 fingerprint
   2) 若 fingerprint 已存在（seen）：跳过（避免重复告警）
   3) 执行规则匹配：
      - 未命中：记录 fingerprint 为 seen（可配置是否记录）
      - 命中：生成 Alert，持久化告警记录，并调用 notifier 发送
   4) 将 fingerprint 持久化为 seen（保证幂等）
4. 将 new_cursor 写入 StateStore（cursor 持久化）

### 8.3 失败处理策略（v0）

- Source 拉取失败：记录错误与 source_key，下一个轮询周期继续
- 429/限流：退避重试（指数退避 + jitter），并降低并发
- 鉴权失败：明确报错（提示缺少 token/权限不足）
- 通知失败：记录失败原因（v0 可不做队列重试，但要可追踪）

## 9. 配置设计（建议）

v0 建议支持以下配置项（可以用 YAML/TOML/JSON 任一形式落地）：

- poll_interval_seconds：轮询间隔
- watch_keywords：关键词列表（如 deepseek、qwen 等）
- sources：
  - github：
    - repos：["vllm-project/vllm", "sgl-project/sglang"]
    - monitor：
      - issues: true
      - pulls: true
    - token_env：GITHUB_TOKEN（可选，建议配）
  - huggingface：
    - orgs：["deepseek-ai"]
    - token_env：HF_TOKEN（可选）
  - modelscope：
    - orgs：["deepseek-ai"]
- notify：
  - welink：
    - webhook_env：WELINK_WEBHOOK_URL
  - email：
    - smtp_host / smtp_port / user_env / password_env / to_list

## 10. 演进路线（建议）

- v0：GitHub（PR/Issue）+ SQLite 去重 + WeLink 通知（可跑闭环）
- v1：接入 HuggingFace + ModelScope，增强规则（正则/白名单/事件类型）
- v2：告警重试队列、失败补偿、webhook 实时化、可观测性面板

