# Aenea contributor instructions

## Scope and architecture

- Aenea is a multi-application monorepo. RAID is a scenario, not the product identity.
- Use Python 3.13 and uv for Python packages. Commit uv.lock after dependency changes.
- Applications live under apps/; reusable contracts belong under packages/.
- Do not create empty CRM, orchestration or notification services ahead of requirements.
- The initial Telegram integration is a user client with read-only application behavior.
- Process only explicitly selected group IDs. Exclude private dialogs by default.
- Do not add sending, joining, reactions, typing or read acknowledgements to the reader.
- Keep matching independent of Telegram transport and validate it with offline fixtures when implemented.

## Credentials

- Aenea has no configured credential store yet. Authenticated work is blocked until an exact store reference and environment profile are declared.
- Do not infer a store from ICA or Codex infrastructure, read old credential files, change CLI defaults or fall back to another vault.
- Use the declared store’s native process injection. Never print secrets, put literal secrets in command arguments or Git, or generate plaintext dotenv files.
- Telegram sessions authorize account access. Keep session material out of Git and logs and follow the declared storage policy.
- No credentials are needed for packaging checks. CI must remain offline with respect to Telegram.

## Checks

```sh
uv sync --locked --all-packages
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked --package aenea-telegram-agent aenea-telegram --help
uv run --locked --package aenea-telegram-agent aenea-telegram --version
uv build --all-packages
```

Add behavior tests when behavior is introduced; do not claim this scaffold reads Telegram.
