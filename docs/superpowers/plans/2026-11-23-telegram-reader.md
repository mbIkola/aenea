# Telegram Reader: план реализации

**Цель:** первый живой POC Telethon: явный вход с сохранением StringSession
в Proton Pass, список групп, новые сообщения одной выбранной группы.

**Архитектура:** один CLI. Конфигурация поступает через native `pass-cli run`
из двух reference-профилей dev. Команда `login` создаёт отдельный custom item
`aenea/telegram-session`, hidden-поле `secret`, через JSON stdin. Существующий
item не перезаписывается. `groups` и `watch` никогда не инициируют вход.
Сессия и entity cache находятся только в памяти процесса; session-файлов нет.

**Стек:** Python 3.13, Telethon 1.x, argparse, unittest, Proton Pass CLI 2.7.1.

## 1. Конфигурация и хранилище

- [x] Создать `tests/test_telegram.py`: отклонение пустых/pass:// значений,
  неверного окружения и неверной сессии до сетевого вызова; отказ при существующем
  item или ошибке Proton; сессия передаётся только JSON stdin, stdout/stderr
  подпроцесса не публикуются. Запуск: `uv run --locked --package
  aenea-telegram-agent python -m unittest discover -s tests -v` — сначала RED.
- [x] Реализовать `config.py` (dataclass с repr=False, обязательный AENEA_ENV=dev)
  и `session_store.py` (явный vault aenea, список metadata без show-secrets,
  проверка уникальности имени, создание hidden secret через stdin).

## 2. Клиент и команды

- [x] Написать offline-тесты с fake Telegram client: `groups` выводит только
  группы, `watch` отвергает неизвестную группу и личный диалог, обработчик
  не выводит события других групп. Неавторизованная сессия не вызывает вход;
  отключение выполняется при ошибках. Проверить RED.
- [x] Реализовать `reader.py`: login вручную через send_code_request/sign_in,
  код/2FA через неблокирующий masked-ввод `/dev/tty`, никакого sign_up. Сохранить StringSession после входа;
  при неудаче сохранения попытаться отозвать только новый вход через log_out.
  `groups` получает диалоги без updates; `watch` использует NewMessage для одной
  группы, без catch_up, истории, send/read acknowledgements и join.
- [x] Обновить `cli.py`: login/groups/watch --chat-id, безопасные ошибки без
  текстов исключений, JSON lines (экранирует терминальные управляющие символы),
  Ctrl+C завершает чтение. Никакой автоматической повторной авторизации.

## 3. Профили, документация и проверки

- [x] Добавить `configs/telegram/dev.login.env.example` (только Telegram
  api_id/api_hash/phone) и `dev.reader.env.example` (api_id/api_hash/session).
- [x] Описать копирование в игнорируемые .env-файлы, login → groups → watch,
  ограничения StringSession (нет checkpoints/replay), отзыв через Telegram,
  восстановление только явным действием пользователя. Обновить README,
  credentials, архитектуру и CI offline-тестами.
- [x] Выполнить unittest, ruff, help/version и сборку всех пакетов.
  Live-вход выполняется пользователем в своём терминале с кодом/2FA;
  не считать offline-тесты доказательством live-подключения.

## Границы и риски

Не добавлять Writer, реакции, join, LLM, Langfuse, SQLite доменных данных.
Read-only — ограничение действий приложения, а не Telegram permission scope.
Список диалогов Telegram технически содержит metadata личных диалогов;
не выводить их и не загружать их историю. Telethon получает transport updates,
но обработчик не извлекает текст событий вне выбранной группы.

StringSession не хранит update checkpoint, поэтому POC показывает новые события
во время подключения и не обещает восстановление пропусков. Изменение
авторизационной сессии нельзя записывать через argv: при обнаружении изменения
остановиться с безопасной ошибкой и инструкцией ручного восстановления.
Параллельные login запрещены организационно: Proton create не имеет атомарного
create-if-absent, перед записью имя проверяется повторно.
