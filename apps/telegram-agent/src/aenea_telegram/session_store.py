"""Write a newly authorized session to the explicit Aenea vault, via stdin only."""

import json
import subprocess

from .config import AppError


class ProtonSessionStore:
    """No default vault, fallback, plaintext file, overwrite, or automatic retry."""

    def _call(self, arguments: list[str], payload: str | None = None) -> str:
        try:
            result = subprocess.run(
                ["pass-cli", "item", *arguments],
                input=payload,
                text=True,
                capture_output=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            raise AppError(
                "Proton Pass недоступен или истёк таймаут. Проверьте pass-cli login. "
                "Не повторяйте создание без проверки item telegram-session."
            ) from None
        if result.returncode:
            raise AppError(
                "Операция Proton Pass не выполнена. Проверьте доступ к vault aenea "
                "и наличие item telegram-session; автоматического повтора нет."
            )
        return result.stdout

    def ensure_absent(self) -> None:
        raw = self._call(
            ["list", "--vault-name", "aenea", "--filter-state", "active", "--output", "json"]
        )
        try:
            items = json.loads(raw)["items"]
            if not isinstance(items, list) or any(
                not isinstance(item, dict) or not isinstance(item.get("title"), str)
                for item in items
            ):
                raise ValueError
        except (ValueError, KeyError, TypeError):
            raise AppError("Неизвестный формат metadata Proton Pass; вход заблокирован.") from None
        if any(item["title"] == "telegram-session" for item in items):
            raise AppError(
                "Item aenea/telegram-session уже существует. Используйте reader-профиль. "
                "Перезапись и повторный вход автоматически не выполняются."
            )

    def save(self, session: str) -> None:
        self.ensure_absent()
        self._call(
            ["create", "custom", "--vault-name", "aenea", "--from-template", "-"],
            json.dumps(
                {
                    "title": "telegram-session",
                    "sections": [],
                    "extra_fields": [{"kind": "hidden", "title": "secret", "value": session}],
                }
            ),
        )
