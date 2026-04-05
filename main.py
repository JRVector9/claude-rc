#!/usr/bin/env python3
"""
claude-rc: Telegram ↔ Claude Code (tmux) bridge
"""
import logging
import sys
from pathlib import Path

import yaml

from bridge.tmux_session import TmuxSession, SessionConfig
from bridge.telegram_bot import TelegramBot


def load_config(path: str = "config/config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict):
    log_file = cfg.get("logging", {}).get("file", "logs/bridge.log")
    level = cfg.get("logging", {}).get("level", "INFO")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ]
    )


def main():
    cfg = load_config()
    setup_logging(cfg)

    logger = logging.getLogger("main")
    logger.info("claude-rc starting")

    # tmux session
    session_cfg = SessionConfig(
        session_name=cfg["tmux"]["session_name"],
        output_log=cfg["bridge"]["output_log"],
        quiet_seconds=cfg["bridge"]["quiet_seconds"],
        max_wait_seconds=cfg["bridge"]["max_wait_seconds"],
        poll_interval=cfg["bridge"]["poll_interval"],
    )
    session = TmuxSession(session_cfg)

    if cfg["tmux"].get("auto_create_session") and not session.session_exists():
        logger.info("Creating tmux session: %s", session_cfg.session_name)
        session.create_session()

    session.start_pipe()
    logger.info("tmux pipe-pane active → %s", session_cfg.output_log)

    # Telegram bot
    bot = TelegramBot(
        token=cfg["telegram"]["bot_token"],
        allowed_chat_ids=cfg["telegram"]["allowed_chat_ids"],
        session=session,
    ).build()

    logger.info("Telegram bot polling started")
    import asyncio
    asyncio.set_event_loop(asyncio.new_event_loop())
    bot.run()


if __name__ == "__main__":
    main()
