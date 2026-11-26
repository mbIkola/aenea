"""A small SDK model factory, with no provider fallback or global key defaults."""

from agents import OpenAIChatCompletionsModel, OpenAIResponsesModel
from openai import AsyncOpenAI

from .config import ModelConfig


def make_client(config: ModelConfig) -> AsyncOpenAI:
    client = AsyncOpenAI(
        api_key=config.api_key,
        base_url=config.base_url,
        max_retries=0,
        timeout=config.timeout_seconds,
    )
    # Aenea selects its account through the explicit project key. Do not inherit
    # organization/project headers from another OpenAI integration in the shell.
    client.organization = None
    client.project = None
    return client


def make_model(config: ModelConfig, client: AsyncOpenAI):
    if config.protocol == "responses":
        return OpenAIResponsesModel(config.model, client)
    return OpenAIChatCompletionsModel(config.model, client)
