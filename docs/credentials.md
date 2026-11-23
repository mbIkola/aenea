# Credential policy

## Current state

No credential store or authenticated environment profile is configured for Aenea.
This is a blocker for Telegram login and live reads, not for local packaging or CI.

Before authenticated implementation, record the selected provider, exact secret references,
explicit environment/profile and native process-injection command in this document without secret values.
Do not guess these settings from another project. ICA and Codex infrastructure credential policies do not choose Aenea’s store.

## Rules

- Inject secrets using the declared provider’s native mechanism and explicit profile.
- Never generate plaintext dotenv files from a secret store.
- Never include literal secrets in shell arguments, Git, logs or fixtures.
- Treat Telegram session files/strings as account credentials; declare their protected persistent storage before login.
- Never silently reauthenticate with old files, another account, vault or provider.
- Do not import, rotate, migrate or delete existing credentials as a setup side effect.

No login command is supplied until the project’s credential process is declared.
