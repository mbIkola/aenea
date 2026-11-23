"""Offline entry point for the Telegram application scaffold."""

import argparse
from importlib.metadata import version


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="aenea-telegram",
        description="Aenea Telegram agent scaffold. Account access is not implemented yet.",
    )
    parser.add_argument("--version", action="version", version=version("aenea-telegram-agent"))
    parser.parse_args()
    parser.print_help()
