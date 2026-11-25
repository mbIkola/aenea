"""Manual fixture-only demo; never consumes the Telegram Inbox."""

import argparse
import asyncio
import json
import logging
import os
from dataclasses import asdict

from .agent import RaidSLAgent, RaidSLRunError
from .catalog import load_fixture_services
from .config import ConfigurationError, load_model_config

DEMO_QUESTION = "Дайте таланты на персонажа Alure. Это проверка тестовых данных."


def main() -> None:
    parser = argparse.ArgumentParser(description="RaidSL: ручной demo на синтетических данных")
    parser.add_argument("command", choices=["demo"])
    parser.parse_args()
    # Do not inherit diagnostic logging that could dump SDK HTTP requests or tool inputs.
    for name in ("openai", "openai.agents", "httpx", "httpx2", "httpcore", "httpcore2"):
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        logger.disabled = True
    try:
        config = load_model_config(os.environ)
        result = asyncio.run(RaidSLAgent(*load_fixture_services(), config).run(DEMO_QUESTION))
        print(json.dumps(asdict(result), ensure_ascii=True), flush=True)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (ConfigurationError, RaidSLRunError) as error:
        parser.exit(1, f"{error}\n")
