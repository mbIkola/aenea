# Aenea · Энея

Autonomous signal discovery and coordination. Named after Aenea from Dan Simmons’ *Hyperion Cantos*.

Aenea will monitor selected sources and turn relevant messages into signals for human review.
The first experiment is a read-only Telegram user client that detects RAID: Shadow Legends talent requests.

## Status

Scaffold only: workspace, package boundaries, CLI, example configuration and CI.
Telegram login, message ingestion, matching and delivery are not implemented.

## Development

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked --all-packages
uv run --locked --package aenea-telegram-agent aenea-telegram --help
uv run --locked --package aenea-telegram-agent aenea-telegram --version
uv run --locked ruff check .
uv run --locked ruff format --check .
uv build --all-packages
```

## Layout

- `apps/telegram-agent/` — Telegram user client application, based on Telethon.
- `packages/contracts/` — reserved home for shared signal contracts; no public schema yet.
- `configs/raid/` — non-secret example profile for the first use case.
- `docs/architecture.md` — boundaries and the next vertical slice.
- `docs/credentials.md` — prerequisite for authenticated development.

An orchestrator, CRM and notification services can become additional applications when needed.

## Account access

No credentials are needed to install, build or run CLI smoke checks.
Before implementing login, declare Aenea’s credential store and an explicit development profile.
See `docs/credentials.md`. Never commit Telegram sessions or place secrets in dotenv files.
