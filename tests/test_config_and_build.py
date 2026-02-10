import json
import os
import pytest

from mrt.config import load_config
from mrt.runner import build_runner


def test_load_config_parses_welink_at_options(tmp_path) -> None:  # noqa: ANN001
    cfg = {
        "poll_interval_seconds": 1,
        "watch_keywords": ["deepseek"],
        "state": {"sqlite_path": ":memory:"},
        "sources": {},
        "notify": {
            "welink": {
                "webhook_env": "WELINK_URL",
                "is_at": True,
                "is_at_all": False,
                "at_accounts": ["u1@corp", "u2@corp"],
            }
        },
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    config = load_config(str(path))
    assert config.welink is not None
    assert config.welink.webhook_env == "WELINK_URL"
    assert config.welink.is_at is True
    assert config.welink.is_at_all is False
    assert config.welink.at_accounts == ("u1@corp", "u2@corp")


def test_build_runner_wires_sources_and_notifiers(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = {
        "poll_interval_seconds": 1,
        "watch_keywords": ["deepseek"],
        "state": {"sqlite_path": ":memory:"},
        "sources": {
            "github": {
                "repos": ["a/b"],
                "monitor": {"issues": True, "pulls": False},
                "token_env": "GITHUB_TOKEN",
            }
        },
        "notify": {"welink": {"webhook_env": "WELINK_URL"}},
    }

    path = tmp_path / "config.json"
    path.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setenv(
        "WELINK_URL",
        "https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard",
    )
    monkeypatch.setenv("GITHUB_TOKEN", "t")

    config = load_config(str(path))
    runner = build_runner(config)

    assert len(runner.sources) == 1
    assert runner.sources[0].key() == "github:a/b:issues"
    assert len(runner.notifiers) == 1
    assert runner.notifiers[0].channel() == "welink"
