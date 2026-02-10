from __future__ import annotations

import argparse
import logging
import os
import time

from .config import load_config
from .runner import build_runner


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mrt", description="Model Release Tracker (polling sentinel)")
    p.add_argument("--config", required=True, help="Path to JSON config file")
    p.add_argument(
        "--log-level",
        default=None,
        help="Log level (DEBUG/INFO/WARNING/ERROR). Defaults to env MRT_LOG_LEVEL or INFO",
    )
    p.add_argument(
        "--status-interval",
        type=int,
        default=None,
        help="Daemon heartbeat interval seconds. Defaults to env MRT_STATUS_INTERVAL_SECONDS or 10. Set 0 to disable.",
    )

    mode = p.add_mutually_exclusive_group(required=False)
    mode.add_argument("--once", action="store_true", help="Run one poll cycle and exit")
    mode.add_argument("--daemon", action="store_true", help="Run forever with poll interval")
    return p


def _resolve_log_level(value: str | None) -> int:
    v = (value or "").strip().upper()
    if not v:
        return logging.INFO
    level = logging.getLevelNamesMapping().get(v)
    if isinstance(level, int):
        return level
    return logging.INFO


def _sources_summary(runner) -> str:  # noqa: ANN001
    parts: list[str] = []
    for s in getattr(runner, "sources", ()):
        try:
            key = s.key()
        except Exception:  # noqa: BLE001
            key = "unknown"
        extras: list[str] = []
        for attr in ("repo", "org"):
            if hasattr(s, attr):
                try:
                    extras.append(f"{attr}={getattr(s, attr)}")
                except Exception:  # noqa: BLE001
                    pass
        extras_s = (", " + ", ".join(extras)) if extras else ""
        parts.append(f"{type(s).__name__}({key}{extras_s})")
    return "; ".join(parts) if parts else "<none>"


def _notifiers_summary(runner) -> str:  # noqa: ANN001
    parts: list[str] = []
    for n in getattr(runner, "notifiers", ()):
        try:
            channel = n.channel()
        except Exception:  # noqa: BLE001
            channel = "unknown"
        parts.append(f"{type(n).__name__}({channel})")
    return "; ".join(parts) if parts else "<none>"


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    env_log_level = os.environ.get("MRT_LOG_LEVEL")
    log_level = _resolve_log_level(args.log_level or env_log_level)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger("mrt")

    config = load_config(args.config)
    runner = build_runner(config)

    status_interval = args.status_interval
    if status_interval is None:
        try:
            status_interval = int(os.environ.get("MRT_STATUS_INTERVAL_SECONDS") or 10)
        except Exception:
            status_interval = 10
    status_interval = max(0, int(status_interval))

    mode = "daemon" if args.daemon and not args.once else "once"
    logger.info("mrt start: mode=%s config=%s", mode, args.config)
    logger.info(
        "config: poll_interval_seconds=%d sqlite_path=%s watch_keywords=%s",
        config.poll_interval_seconds,
        config.sqlite_path,
        ",".join(config.watch_keywords) if config.watch_keywords else "<none>",
    )
    logger.info("sources: %s", _sources_summary(runner))
    logger.info("notifiers: %s", _notifiers_summary(runner))
    if not getattr(runner, "sources", ()):
        logger.warning("no sources configured; nothing will be polled")
    if not getattr(runner, "notifiers", ()):
        logger.warning("no notifiers configured; alerts will be recorded but not delivered")
    if mode == "daemon":
        logger.info(
            "daemon: poll_interval_seconds=%d status_interval_seconds=%d",
            max(1, config.poll_interval_seconds),
            status_interval,
        )

    if args.once or not args.daemon:
        report = runner.run_once()
        logger.info(
            "once done: duration_ms=%d sources=%d events_fetched=%d events_processed=%d matched=%d alerts=%d notify_failures=%d source_errors=%d",
            report.duration_ms,
            len(report.sources),
            report.events_fetched,
            report.events_processed,
            report.events_matched,
            report.alerts_created,
            report.notify_failures,
            report.source_errors,
        )
        return 0

    cycle_id = 0
    last_summary_logged_at = 0.0
    next_heartbeat_at = time.monotonic() + status_interval if status_interval > 0 else float("inf")
    acc = {
        "events_fetched": 0,
        "events_processed": 0,
        "events_matched": 0,
        "alerts_created": 0,
        "notify_failures": 0,
        "source_errors": 0,
    }

    while True:
        cycle_id += 1
        try:
            report = runner.run_once()
        except Exception:  # noqa: BLE001
            logger.exception("cycle crashed: id=%d", cycle_id)
            time.sleep(5)
            continue

        now = time.monotonic()
        acc["events_fetched"] += report.events_fetched
        acc["events_processed"] += report.events_processed
        acc["events_matched"] += report.events_matched
        acc["alerts_created"] += report.alerts_created
        acc["notify_failures"] += report.notify_failures
        acc["source_errors"] += report.source_errors

        should_log_cycle = (
            status_interval <= 0
            or report.alerts_created > 0
            or report.notify_failures > 0
            or report.source_errors > 0
            or (now - last_summary_logged_at) >= max(1, status_interval)
        )
        if should_log_cycle:
            logger.info(
                "cycle summary: id=%d duration_ms=%d events_fetched=%d events_processed=%d matched=%d alerts=%d notify_failures=%d source_errors=%d",
                cycle_id,
                report.duration_ms,
                acc["events_fetched"],
                acc["events_processed"],
                acc["events_matched"],
                acc["alerts_created"],
                acc["notify_failures"],
                acc["source_errors"],
            )
            acc = {k: 0 for k in acc}
            last_summary_logged_at = now

        sleep_seconds = max(1, config.poll_interval_seconds)
        sleep_end = time.monotonic() + sleep_seconds
        while True:
            now = time.monotonic()
            if now >= sleep_end:
                break

            if status_interval > 0 and now >= next_heartbeat_at:
                remaining = max(0, int(sleep_end - now))
                logger.info(
                    "daemon alive: cycles=%d next_poll_in=%ds last_duration_ms=%d last_alerts=%d last_notify_failures=%d last_source_errors=%d",
                    cycle_id,
                    remaining,
                    report.duration_ms,
                    report.alerts_created,
                    report.notify_failures,
                    report.source_errors,
                )
                next_heartbeat_at = now + status_interval

            remaining_s = sleep_end - now
            if status_interval > 0:
                next_tick = max(0.2, next_heartbeat_at - now)
                time.sleep(min(remaining_s, next_tick))
            else:
                time.sleep(min(remaining_s, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
