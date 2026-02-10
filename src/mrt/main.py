from __future__ import annotations

import argparse
import time

from .config import load_config
from .runner import build_runner


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mrt", description="Model Release Tracker (polling sentinel)")
    p.add_argument("--config", required=True, help="Path to JSON config file")

    mode = p.add_mutually_exclusive_group(required=False)
    mode.add_argument("--once", action="store_true", help="Run one poll cycle and exit")
    mode.add_argument("--daemon", action="store_true", help="Run forever with poll interval")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = load_config(args.config)
    runner = build_runner(config)

    if args.once or not args.daemon:
        runner.run_once()
        return 0

    while True:
        runner.run_once()
        time.sleep(max(1, config.poll_interval_seconds))


if __name__ == "__main__":
    raise SystemExit(main())

