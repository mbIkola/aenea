"""Manual RaidSL runs with explicitly selected catalogue tools; no Telegram Inbox."""

import argparse
import asyncio
import json
import logging
import os
from dataclasses import asdict

from .agent import RaidSLAgent, RaidSLRunError
from .catalog import load_fixture_services
from .catalog_cli import CatalogCLISettings, CatalogCLITools
from .config import ConfigurationError, load_model_config
from .runtime_tools import FixtureTools


def main() -> None:
    parser = argparse.ArgumentParser(description="RaidSL: ручной запуск без Telegram Inbox")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Ручной запрос к выбранному backend каталога")
    demo.add_argument("--character", default="Alure")
    demo.add_argument("--mode", choices=["all", "pve", "pvp"], default="all")
    ask = commands.add_parser("ask", help="Передать явно заданный ручной вопрос модели")
    ask.add_argument("--question", required=True)
    args = parser.parse_args()
    # Do not inherit diagnostic logging that could dump SDK HTTP requests or tool inputs.
    for name in ("openai", "openai.agents", "httpx", "httpx2", "httpcore", "httpcore2"):
        logger = logging.getLogger(name)
        logger.handlers = [logging.NullHandler()]
        logger.propagate = False
        logger.disabled = True
    try:
        config = load_model_config(os.environ)
        backend = os.environ.get("RAIDSL_CATALOG_BACKEND", "fixture")
        if backend == "fixture":
            tools = FixtureTools(*load_fixture_services())
        elif backend == "cli":
            tools = CatalogCLITools(CatalogCLISettings.from_env(os.environ))
        else:
            raise ConfigurationError("RAIDSL_CATALOG_BACKEND должен быть fixture либо cli.")
        question = (
            args.question
            if args.command == "ask"
            else (f"Дайте таланты на персонажа {args.character}. Режим: {args.mode}.")
        )
        result = asyncio.run(RaidSLAgent(config, tools).run(question))
        print(json.dumps(asdict(result), ensure_ascii=True), flush=True)
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    except (ConfigurationError, RaidSLRunError) as error:
        parser.exit(1, f"{error}\n")
