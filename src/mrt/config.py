from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping


def _require_dict(value: Any, *, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Expected object at {where}, got {type(value)}")
    return value


def _get_bool(d: Mapping[str, Any], key: str, default: bool) -> bool:
    v = d.get(key, default)
    return bool(v)


def _get_int(d: Mapping[str, Any], key: str, default: int) -> int:
    v = d.get(key, default)
    if isinstance(v, bool):
        return default
    try:
        return int(v)
    except Exception:
        return default


def _get_str(d: Mapping[str, Any], key: str, default: str | None = None) -> str | None:
    v = d.get(key, default)
    if v is None:
        return None
    return str(v)


def _get_str_list(d: Mapping[str, Any], key: str, default: list[str]) -> list[str]:
    v = d.get(key, default)
    if v is None:
        return list(default)
    if isinstance(v, list):
        return [str(x) for x in v]
    return list(default)


@dataclass(frozen=True, slots=True)
class GitHubSourceConfig:
    """
    GitHub 数据源配置（Repo 维度）。

    repos:
      - 形如 "owner/repo" 的字符串列表
    monitor_issues / monitor_pulls:
      - 是否分别监控 Issues / Pull Requests
    token_env:
      - GitHub Token 的环境变量名（可选，不配置则匿名访问，易触发限流）
    """

    repos: tuple[str, ...]
    monitor_issues: bool
    monitor_pulls: bool
    token_env: str | None


@dataclass(frozen=True, slots=True)
class HuggingFaceSourceConfig:
    """
    HuggingFace 数据源配置（组织/用户维度）。
    """

    orgs: tuple[str, ...]
    token_env: str | None


@dataclass(frozen=True, slots=True)
class ModelScopeSourceConfig:
    """
    ModelScope 数据源配置（组织维度）。
    """

    orgs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeLinkNotifyConfig:
    """
    WeLink 群机器人 webhook 通知配置（对齐 docs/welink-webhook-usecase.md）。

    webhook_env:
      - webhook URL 的环境变量名（URL 需要包含 token 与 channel=standard）
    is_at / at_accounts:
      - 是否 @ 指定人员；当 is_at 为 true 时，at_accounts 至少 1 个，最多 10 个
    is_at_all:
      - 是否 @ 全员（会在消息前自动加 @all）
    """

    webhook_env: str
    is_at: bool = False
    is_at_all: bool = False
    at_accounts: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EmailNotifyConfig:
    """
    邮件通知配置（SMTP）。
    """

    smtp_host: str
    smtp_port: int
    user_env: str
    password_env: str
    to_list: tuple[str, ...]
    use_tls: bool = True


@dataclass(frozen=True, slots=True)
class AppConfig:
    """
    应用总配置（v0 版本）。

    poll_interval_seconds:
      - 轮询间隔（daemon 模式下生效）
    watch_keywords:
      - 关键词列表（大小写不敏感），用于规则匹配
    sqlite_path:
      - SQLite 状态库路径（负责 cursor/去重/告警记录）
    """

    poll_interval_seconds: int
    watch_keywords: tuple[str, ...]
    sqlite_path: str
    github: GitHubSourceConfig | None
    huggingface: HuggingFaceSourceConfig | None
    modelscope: ModelScopeSourceConfig | None
    welink: WeLinkNotifyConfig | None
    email: EmailNotifyConfig | None

    def resolve_env(self, env_name: str | None) -> str | None:
        if not env_name:
            return None
        return os.environ.get(env_name)


def load_config(config_path: str) -> AppConfig:
    """
    v0 约定：使用 JSON 作为配置落地形式，避免引入第三方 YAML 解析依赖。

    JSON 顶层结构（示意）：
    {
      "poll_interval_seconds": 300,
      "watch_keywords": ["deepseek", "qwen"],
      "state": { "sqlite_path": "./mrt_state.sqlite3" },
      "sources": { ... },
      "notify": { ... }
    }
    """
    with open(config_path, "rb") as f:
        raw = json.loads(f.read().decode("utf-8"))

    root = _require_dict(raw, where="$")
    poll_interval_seconds = _get_int(root, "poll_interval_seconds", 300)
    watch_keywords = tuple(_get_str_list(root, "watch_keywords", []))

    state = _require_dict(root.get("state", {"sqlite_path": "./mrt_state.sqlite3"}), where="$.state")
    sqlite_path = str(state.get("sqlite_path") or "./mrt_state.sqlite3")

    sources = _require_dict(root.get("sources", {}), where="$.sources")

    github_cfg: GitHubSourceConfig | None = None
    if isinstance(sources.get("github"), dict):
        gh = _require_dict(sources["github"], where="$.sources.github")
        repos = tuple(_get_str_list(gh, "repos", []))
        monitor = _require_dict(gh.get("monitor", {}), where="$.sources.github.monitor")
        github_cfg = GitHubSourceConfig(
            repos=repos,
            monitor_issues=_get_bool(monitor, "issues", True),
            monitor_pulls=_get_bool(monitor, "pulls", True),
            token_env=_get_str(gh, "token_env", None),
        )

    hf_cfg: HuggingFaceSourceConfig | None = None
    if isinstance(sources.get("huggingface"), dict):
        hf = _require_dict(sources["huggingface"], where="$.sources.huggingface")
        hf_cfg = HuggingFaceSourceConfig(
            orgs=tuple(_get_str_list(hf, "orgs", [])),
            token_env=_get_str(hf, "token_env", None),
        )

    ms_cfg: ModelScopeSourceConfig | None = None
    if isinstance(sources.get("modelscope"), dict):
        ms = _require_dict(sources["modelscope"], where="$.sources.modelscope")
        ms_cfg = ModelScopeSourceConfig(orgs=tuple(_get_str_list(ms, "orgs", [])))

    notify = _require_dict(root.get("notify", {}), where="$.notify")

    welink_cfg: WeLinkNotifyConfig | None = None
    if isinstance(notify.get("welink"), dict):
        wl = _require_dict(notify["welink"], where="$.notify.welink")
        webhook_env = str(wl.get("webhook_env") or "WELINK_WEBHOOK_URL")
        at_accounts = tuple(_get_str_list(wl, "at_accounts", []))
        welink_cfg = WeLinkNotifyConfig(
            webhook_env=webhook_env,
            is_at=_get_bool(wl, "is_at", bool(at_accounts)),
            is_at_all=_get_bool(wl, "is_at_all", False),
            at_accounts=at_accounts,
        )

    email_cfg: EmailNotifyConfig | None = None
    if isinstance(notify.get("email"), dict):
        em = _require_dict(notify["email"], where="$.notify.email")
        to_list = tuple(_get_str_list(em, "to_list", []))
        email_cfg = EmailNotifyConfig(
            smtp_host=str(em.get("smtp_host") or ""),
            smtp_port=_get_int(em, "smtp_port", 587),
            user_env=str(em.get("user_env") or ""),
            password_env=str(em.get("password_env") or ""),
            to_list=to_list,
            use_tls=_get_bool(em, "use_tls", True),
        )

    return AppConfig(
        poll_interval_seconds=poll_interval_seconds,
        watch_keywords=watch_keywords,
        sqlite_path=sqlite_path,
        github=github_cfg,
        huggingface=hf_cfg,
        modelscope=ms_cfg,
        welink=welink_cfg,
        email=email_cfg,
    )
