"""Explicit dev profile; credentials arrive resolved through native pass-cli run."""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal


class ConfigurationError(ValueError):
    """Missing or unsupported model configuration; never includes secret values."""


@dataclass(frozen=True, slots=True)
class ModelConfig:
    provider: Literal["openai", "packet"]
    model: str
    base_url: str
    protocol: Literal["responses", "chat_completions"]
    api_key: str = field(repr=False)
    max_turns: int = 5
    max_output_tokens: int = 2048
    timeout_seconds: float = 60


def load_model_config(env: Mapping[str, str]) -> ModelConfig:
    if env.get("AENEA_ENV") != "dev":
        raise ConfigurationError("Для RaidSL требуется явный профиль AENEA_ENV=dev.")
    provider = env.get("RAIDSL_PROVIDER", "")
    endpoints = {
        "openai": ("https://api.openai.com/v1", "responses"),
        "packet": ("https://api.packet.ai/v1", "chat_completions"),
    }
    if provider not in endpoints:
        raise ConfigurationError("Выберите RAIDSL_PROVIDER=openai либо packet.")
    base_url, protocol = endpoints[provider]
    if env.get("RAIDSL_BASE_URL", base_url).rstrip("/") != base_url:
        raise ConfigurationError("RAIDSL_BASE_URL не соответствует выбранному провайдеру.")
    key = env.get("RAIDSL_API_KEY", "").strip()
    if not key or key.startswith(("pass://", "keychain://")):
        raise ConfigurationError("RAIDSL_API_KEY должен быть разрешён через pass-cli run.")
    model = env.get("RAIDSL_MODEL", "").strip()
    if not model:
        raise ConfigurationError("Укажите RAIDSL_MODEL явно.")
    try:
        turns = int(env.get("RAIDSL_MAX_TURNS", "5"))
        tokens = int(env.get("RAIDSL_MAX_OUTPUT_TOKENS", "2048"))
        timeout = float(env.get("RAIDSL_TIMEOUT_SECONDS", "60"))
        if not (1 <= turns <= 10 and 128 <= tokens <= 4096 and 0 < timeout <= 120):
            raise ValueError
        if not math.isfinite(timeout):
            raise ValueError
    except ValueError:
        raise ConfigurationError("Некорректные ограничения шагов, токенов или времени.") from None
    return ModelConfig(provider, model, base_url, protocol, key, turns, tokens, timeout)
