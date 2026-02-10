# Model Release Tracker v0 使用说明

## 1. 解决什么问题

Model Release Tracker（MRT）用于以“轮询”的方式持续监控多个社区/平台（GitHub / HuggingFace / ModelScope 等）的更新动态，并在发现与关注对象相关的更新时触发告警通知（如 WeLink 群机器人、邮件等）。

适用场景示例：

- 你希望第一时间知道 vLLM / SGLang 仓库里是否出现 “DeepSeek / Qwen” 相关的 Issue/PR 更新；
- 你希望第一时间知道 HuggingFace 上 deepseek-ai 组织下是否出现模型新增/模型卡更新；
- 你希望第一时间知道 ModelScope（魔搭）上 deepseek-ai 组织下是否出现新模型；
- 告警需要具备幂等能力：程序重启后不会重复告警同一事件。

## 2. 快速开始（端到端示例）

### 2.1 准备环境变量（强烈建议只用环境变量放密钥）

MRT 的配置里用的是 `*_env` 字段：它们表示“环境变量名”，而不是密钥/URL 本身。

例如：

- `token_env: "GITHUB_TOKEN"` 表示去读取环境变量 `GITHUB_TOKEN` 的值作为 GitHub token
- `webhook_env: "WELINK_WEBHOOK_URL"` 表示去读取环境变量 `WELINK_WEBHOOK_URL` 的值作为 WeLink webhook URL

GitHub（可选但强烈建议配置，否则容易遇到 403 rate limit）：

- `GITHUB_TOKEN`：GitHub token，用于提升限流配额

WeLink（可选）：

- `WELINK_WEBHOOK_URL`：群 webhook 机器人地址，需包含 token 与 channel 参数，例如：
  - `https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=xxx&channel=standard`

HuggingFace（可选）：

- `HF_TOKEN`：访问 HuggingFace 的 token（若只访问公开信息可不配置）

在 Linux / bash 中可这样设置（注意不要把 token 写进 JSON 配置文件，也不要在命令行历史里泄露）：

```bash
export GITHUB_TOKEN="ghp_xxx"
export WELINK_WEBHOOK_URL="https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=xxx&channel=standard"
export HF_TOKEN="hf_xxx"
```

### 2.2 编写配置文件（JSON）

示例：监控 GitHub 的 vLLM/SGLang，同时监控 HuggingFace 与 ModelScope 的 deepseek-ai，并通过 WeLink 群机器人通知：

```json
{
  "poll_interval_seconds": 300,
  "watch_keywords": ["deepseek", "qwen"],
  "state": { "sqlite_path": "./mrt_state.sqlite3" },
  "sources": {
    "github": {
      "repos": ["vllm-project/vllm", "sgl-project/sglang"],
      "monitor": { "issues": true, "pulls": true },
      "token_env": "GITHUB_TOKEN"
    },
    "huggingface": { "orgs": ["deepseek-ai"], "token_env": "HF_TOKEN" },
    "modelscope": { "orgs": ["deepseek-ai"] }
  },
  "notify": {
    "welink": {
      "webhook_env": "WELINK_WEBHOOK_URL",
      "is_at": false,
      "is_at_all": false,
      "at_accounts": []
    }
  }
}
```

### 2.3 运行

一次执行（适合放到 cron 或手工验证）：

```bash
source $(conda info --base)/etc/profile.d/conda.sh
conda activate box

PYTHONPATH=src python -m mrt --config /path/to/config.json --once
```

常驻轮询（daemon）：

```bash
PYTHONPATH=src python -m mrt --config /path/to/config.json --daemon
```

## 3. 配置参数说明（逐项）

### 3.1 顶层参数

- `poll_interval_seconds`（int，可选，默认 300）
  - daemon 模式下两次轮询之间的 sleep 间隔（秒）
- `watch_keywords`（string[]，可选，默认 []）
  - 关键词列表，规则层会对 `event.title` 与 `event.summary` 做大小写不敏感匹配
- `state.sqlite_path`（string，可选，默认 `./mrt_state.sqlite3`）
  - SQLite 状态库路径，用于：
    - cursor：每个 source 的进度
    - seen_events：fingerprint 去重集合
    - alerts：告警落库
    - notify_failures：通知失败留痕

### 3.2 sources.github

- `repos`（string[]）
  - 形如 `owner/repo` 的仓库列表
- `monitor.issues`（bool，可选，默认 true）
  - 是否监控 Issues（注意：内部会过滤 PR 伪装成的 issue 记录）
- `monitor.pulls`（bool，可选，默认 true）
  - 是否监控 Pull Requests
- `token_env`（string，可选）
  - GitHub token 的环境变量名；若为空则匿名访问（更易触发 403 rate limit exceeded）
  - 典型写法：`"token_env": "GITHUB_TOKEN"`，并在运行前 `export GITHUB_TOKEN="..."` 或通过进程环境注入

### 3.3 sources.huggingface

- `orgs`（string[]）
  - 组织/用户列表，例如 `["deepseek-ai"]`
- `token_env`（string，可选）
  - HuggingFace Token 的环境变量名

### 3.4 sources.modelscope

- `orgs`（string[]）
  - 组织列表，例如 `["deepseek-ai"]`

说明：
- v0 通过解析组织页 HTML 中的模型链接来检测新增模型，属于“尽力而为”的实现，后续可演进为更稳定的 API 拉取方式。

### 3.5 notify.welink

- `webhook_env`（string，可选，默认 `WELINK_WEBHOOK_URL`）
  - WeLink webhook URL 的环境变量名（不是 URL 本身）
  - URL 需要包含 `token` 与 `channel` 参数，例如：
    - `https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=xxx&channel=standard`
- `is_at`（bool，可选，默认：当 `at_accounts` 非空时为 true，否则 false）
  - 是否 @ 指定人员
- `at_accounts`（string[]，可选，默认 []）
  - 被 @ 人员的 userid 列表（最多 10 个）
  - MRT 会在消息正文前自动补齐 `@userid`，并按 WeLink 规则携带 `atAccounts`
- `is_at_all`（bool，可选，默认 false）
  - 是否 @ 全员；为 true 时 MRT 会在消息正文前自动补齐 `@all`

重要说明（与 WeLink 官方规则一致）：

- `content.text` 中必须出现 `@userid` 或 `@all/@所有人` 才会在群内高亮；
- 当 `is_at=true` 时，`at_accounts` 不能为空，且其中的 userid 必须正确，否则对方无法收到提醒；
- 接口侧会校验 `timeStamp` 有效期（10 分钟内），MRT 会在发送时生成当前毫秒时间戳与全局唯一 uuid。

### 3.6 notify.email（可选）

- `smtp_host`（string）
- `smtp_port`（int，可选，默认 587）
- `user_env`（string）
- `password_env`（string）
- `to_list`（string[]）
- `use_tls`（bool，可选，默认 true）

## 4. 常见问题

### 4.0 配置文件里应该写 notifiers 还是 notify？

配置文件使用 `notify` 作为顶层 key（见 [config.py](file:///mnt/c/AIWorks/AICode/projects/model-release-tracker/src/mrt/config.py#L145-L231) 的 JSON 结构约定）。启动日志里打印的是 runner 里“实际装配出来的 notifiers 列表”，这两个词容易混淆。

### 4.1 为什么不会重复告警？

每条事件都会生成 fingerprint（幂等键），并写入 SQLite 的 `seen_events` 表。即使进程重启或重复拉取到相同事件，也会因为 fingerprint 已存在而跳过发送。

### 4.2 为什么 GitHub 会报 403: rate limit exceeded？

常见原因是 GitHub token 没有生效，程序退化成匿名访问（配额更低）。请检查：

- 配置里 `sources.github.token_env` 写的是环境变量名（例如 `GITHUB_TOKEN`），而不是 token 本身
- 运行进程的环境中确实存在该环境变量（例如 `echo "$GITHUB_TOKEN"` 有值）
- token 仍然有效且未过期

### 4.3 如何验证 WeLink webhook 正常？

优先用 docs/welink-webhook-usecase.md 中的 curl 示例验证 webhook 本身可用，然后再配置到 MRT，通过 `--once` 运行观察群内是否收到消息。
