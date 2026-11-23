# Architecture and first slice

Aenea discovers signals in external sources. The product is independent of the first business or game scenario.

## Boundaries

- `apps/telegram-agent`: owns the Telethon connection and conversion of allowed source messages into signals.
- `packages/contracts`: will define the smallest useful shared signal schema once the first producer is implemented.
- `configs/raid`: holds scenario-specific, non-secret settings. It must not contain account credentials.

The root is a virtual uv workspace. Each member is an independently buildable Python package with a shared dependency lockfile.
There is no orchestrator, CRM, notification service, database or language-model dependency in this scaffold.

## Next vertical slice

1. Declare the credential store, exact secret references and a development profile.
2. Authorize a user account interactively and store its session according to that policy.
3. Receive new messages from an explicit group-ID allowlist, excluding private dialogs.
4. Match talent requests and extract the requested character name using offline examples first.
5. Persist local review signals containing source chat/message IDs, original text, timestamp and extracted name.
6. Verify restart recovery, deduplication and connection health.

Read-only is an application restriction, not a Telegram permission scope. The reader must not send messages, join groups, react, emit typing status or explicitly acknowledge reads.
The example profile is documentation, not a supported configuration interface yet.

## Dependencies

Telethon is consumed as a regular package, with its exact version recorded in uv.lock.
Upstream moved from GitHub to https://codeberg.org/Lonami/Telethon; no fork or vendored source is needed.
