# Aenea · Энея

Система поиска сигналов и координации их обработки. Названа в честь Энеи из цикла Дэна Симмонса «Песни Гипериона».

Aenea будет наблюдать за выбранными источниками и превращать сообщения в отдельные кейсы. Первый сценарий — запросы талантов RAID: Shadow Legends в Telegram. Другой сценарий — обращения потенциальных клиентов автосервиса.

## Текущее состояние

Подготовлен uv workspace, границы пакетов и CI. Реализован первый Telegram Reader POC на Telethon: `login` с сохранением StringSession в Proton Pass, `groups` и `watch --chat-id --db`. Запуск описан в [руководстве Reader](docs/telegram-reader.md).

Реализован SQLite Inbox и первый [срез регистрации и маршрутизации агентов](docs/agent-routing.md): AgentHub, Router по паспортам и dummy RaidSL. Агент возвращает карточку «это моё, но пока игнорируем»; локальный IgnoreWriter сохраняет терминальный результат без отправки в Telegram. Кейсы, игровая логика, LLM и внешняя доставка не реализованы. Восстановления пропусков и истории редактирований нет.

## Принятые решения MVP

Один процесс с отдельными модулями и SQLite. Центральная сущность — `Case`, состояние которого сохраняется между сообщениями и перезапусками. Hosted Langfuse отвечает за наблюдаемость. OpenAI предусмотрен на будущее; LangGraph и отдельный брокер пока не нужны. CRM подключается независимым потребителем событий.

Начальный Telegram-клиент читает явно разрешённые группы отдельным аккаунтом. Ответы и другие внешние действия сначала проходят dry-run; разрешение на отправку задаётся отдельно.

## Разработка

Нужны Python 3.13 и [uv](https://docs.astral.sh/uv/).

```sh
uv sync --locked --all-packages
uv run --locked --package aenea-telegram-agent aenea-telegram --help
uv run --locked --package aenea-telegram-agent aenea-telegram --version
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked --package aenea-telegram-agent python -m unittest discover -s tests -v
uv build --all-packages
```

Для этих offline-проверок ключи не нужны.

## Структура

- `apps/telegram-agent/` — пользовательский Telegram Reader на Telethon с CLI.
- `configs/telegram/` — reference-профили первого входа и повторного чтения.
- `packages/contracts/` — `IncomingMessage`, ключ сообщения и результат приёма без зависимости от Telethon/SQLite.
- `packages/agents/` — независимые registry, Router, Dispatcher, IgnoreWriter и dummy RaidSL.
- `configs/raid/` — несекретный пример профиля первого сценария.
- `docs/` — архитектура, диаграммы и правила конфигурации на русском.
- `.env.example` — reference-шаблон dev с Proton Pass URI и несекретными настройками.

## Credentials

Хранилище проекта — Proton Pass vault `aenea`. Локальный `.env` содержит только ссылки и несекретные настройки; значения пользователь хранит в vault. Отсутствующие OpenAI и Telegram credentials зарезервированы ссылками, а не выдуманными ключами. См. [точную адресацию и ограничения запуска](docs/credentials.md).
