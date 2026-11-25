"""Explicit in-process registry; no remote discovery or dynamic code loading."""

import re
import unicodedata
from collections.abc import Iterable

from .contracts import Agent, AgentDescriptor


def normalize_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


class AgentHub:
    def __init__(self, agents: Iterable[Agent] = ()):
        self._agents: dict[str, Agent] = {}
        for agent in agents:
            self.register(agent)

    def register(self, agent: Agent) -> None:
        descriptor = agent.descriptor
        if not re.fullmatch(r"[a-z][a-z0-9_]*", descriptor.agent_id):
            raise ValueError("Agent ID must be a lowercase identifier")
        if descriptor.agent_id in self._agents:
            raise ValueError(f"Duplicate agent ID: {descriptor.agent_id}")
        if not descriptor.trigger_phrases or any(
            not normalize_text(phrase)
            for phrase in (*descriptor.trigger_phrases, *descriptor.exclude_phrases)
        ):
            raise ValueError("Agents must declare non-empty trigger phrases")
        self._agents[descriptor.agent_id] = agent

    def descriptors(self) -> tuple[AgentDescriptor, ...]:
        return tuple(self._agents[key].descriptor for key in sorted(self._agents))

    def get(self, agent_id: str) -> Agent:
        return self._agents[agent_id]
