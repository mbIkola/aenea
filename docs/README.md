# Документация Aenea

- [Архитектура и границы компонентов](architecture.md): принятые решения MVP, сущности, flow и sequence diagram, обработка поздних ответов, CRM и надёжность.
- [Конфигурация и credentials](credentials.md): vault `aenea`, reference-профиль dev, hosted Langfuse и зарезервированные интеграции.
- [Telegram Reader POC](telegram-reader.md): вход с сессией в Proton Pass, список групп и чтение выбранной группы.
- [Registry и dummy RaidSL](agent-routing.md): AgentHub → Router → Agent → Action → Writer, локальная карточка и сохраняемый `ignore`.
- [RaidSL Runner](raidsl-runner.md): Agents SDK, OpenAI/Packet, fixture-tools и будущий каталог.
- [Идея локального интерфейса](superpowers/specs/2026-11-24-local-desktop-ui-idea.md): Windows/macOS, визард входа и выбор групп; status: idea to review.
- [План первоначального scaffold](superpowers/plans/2026-11-23-scaffold.md): историческая запись об уже подготовленном каркасе.

Архитектура описывает целевое поведение. Наличие документации, конфигурационных ссылок и зависимостей не означает, что компоненты уже реализованы.
