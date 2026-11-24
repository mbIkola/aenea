# План реализации Telegram Inbox

> **Для агентов:** выполнять задачи по порядку с помощью `subagent-driven-development`
> или `executing-plans`; проверять соответствие спецификации и качество кода.

**Цель:** Сохранять новые сообщения выбранной группы в SQLite до подтверждения приёма.

**Архитектура:** Неизменяемый транспортно-независимый контракт передаётся в async Inbox. SQLite синхронно выполняет короткую транзакцию с ограниченным busy timeout. Reader нормализует разрешённую проекцию Telethon, управляющая coroutine получает фатальные ошибки callback.

**Стек:** Python 3.13, uv, stdlib sqlite3/unittest, Telethon 1.46 (зафиксированная версия uv.lock).

## 1. Контракты и SQLite

Файлы: `packages/contracts/src/aenea_contracts/__init__.py`,
`apps/telegram-agent/src/aenea_telegram/inbox.py`, `tests/test_inbox.py`.

- [x] Добавить offline-тесты неизменяемого IncomingMessage, составного MessageKey и StoreResult; SQLite: повтор после переоткрытия, независимость аккаунтов/групп, конфликт устойчивого содержимого, первый снимок, неизвестная версия схемы, rollback при ошибке commit.
- [x] Запустить `uv run --locked --package aenea-telegram-agent python -m unittest discover -s tests -p test_inbox.py -v`, убедиться в отсутствии реализации.
- [x] Реализовать frozen dataclasses с полями спецификации, Inbox Protocol и SQLiteInbox с context manager, одной таблицей messages, user_version=1, UNIQUE ключа и атомарным insert/сравнением. Времена хранить в UTC, JSON канонизировать, несовместимые metadata_version отклонять. Для стабильного сравнения исключать только явно перечисленные поля состояния из поддержанной проекции.
- [x] Повторить тесты; исходную строку при повторе/конфликте не менять.

## 2. Нормализация Telethon

Файлы: `apps/telegram-agent/src/aenea_telegram/normalization.py`, `tests/test_normalization.py`.

- [x] На реальных offline TL-объектах написать тесты Unicode/entities, peer/reply/topic, внешнего и scheduled reply, forward, photo/document/poll/contact/geo/web preview/service action и неизвестного конструктора. Проверить отсутствие access_hash, file_reference, bytes и любых новых неизвестных полей рекурсивно.
- [x] Запустить отдельный модуль тестов и увидеть отсутствие нормализатора.
- [x] Реализовать `normalize_message(message, *, source_account_id, chat_id, received_at=None) -> IncomingMessage`. Использовать только фиксированные списки разрешённых полей известных конструкторов; неизвестные объекты — имя типа и incomplete. Дополнительных RPC нет. В metadata v1 разделить `content` (устойчивое содержимое) и `snapshot` (счётчики/реакции/результаты опросов).
- [x] Повторить тесты и зафиксировать поддержанный состав проекции.

## 3. Reader и CLI

Файлы: `apps/telegram-agent/src/aenea_telegram/reader.py`, `cli.py`, `tests/test_telegram.py`.

- [x] Добавить failing tests fake Inbox: фильтрация до чтения содержимого, account ID из get_me, await accept до emit, фатальная ошибка даже если Telethon глотает callback exception, запрет новых приёмов после сбоя, drain начатого accept при отмене, отсутствие текста в stdout.
- [x] CLI watch требует `--db PATH`; отсутствие пути отклоняется до соединения. CLI создаёт/закрывает SQLiteInbox; Reader получает только Inbox.
- [x] Передавать ключ и status stored/duplicate после commit. Фатальные ошибки передавать отдельным Future в управляющий цикл; в finally удалить handler и дождаться начатых callback до закрытия Inbox.
- [x] Запустить все offline unittest и устранить регрессии входа/сессии.

## 4. Документация, review и PR

Файлы: `docs/telegram-reader.md`, `README.md`, спецификация Inbox.

- [x] Обновить запуск и статус реализации, ограничения live-only, чувствительность SQLite, правила повторов и метаданных. Не запускать Telegram и не обращаться к credentials ради offline-проверок.
- [x] Проверить соответствие десяти критериям спецификации и выполнить отдельное code review.
- [x] Выполнить scaffold checks из AGENTS.md и unittest; проверить diff и ссылки документации.
- [ ] Создать коммиты, push ветки и PR в `codex/telegram-reader-poc`, чтобы diff содержал только Inbox поверх исходного Reader POC; проверить base/head и URL PR.
