import json
import os
import sys
import tempfile
import unittest


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))


from mrt.config import load_config  # noqa: E402
from mrt.runner import build_runner  # noqa: E402


class TestConfigAndBuild(unittest.TestCase):
    def test_load_config_parses_welink_at_options(self) -> None:
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
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)

            config = load_config(path)
            assert config.welink is not None
            self.assertEqual(config.welink.webhook_env, "WELINK_URL")
            self.assertEqual(config.welink.is_at, True)
            self.assertEqual(config.welink.is_at_all, False)
            self.assertEqual(config.welink.at_accounts, ("u1@corp", "u2@corp"))

    def test_build_runner_wires_sources_and_notifiers(self) -> None:
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
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "config.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False)

            os.environ["WELINK_URL"] = "https://open.welink.huaweicloud.com/api/werobot/v1/webhook/send?token=x&channel=standard"
            os.environ["GITHUB_TOKEN"] = "t"
            try:
                config = load_config(path)
                runner = build_runner(config)
            finally:
                os.environ.pop("WELINK_URL", None)
                os.environ.pop("GITHUB_TOKEN", None)

        self.assertEqual(len(runner.sources), 1)
        self.assertEqual(runner.sources[0].key(), "github:a/b:issues")
        self.assertEqual(len(runner.notifiers), 1)
        self.assertEqual(runner.notifiers[0].channel(), "welink")

