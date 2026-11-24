"""Small contracts; agents do not receive transport clients or credentials."""

from dataclasses import asdict, dataclass
from typing import Literal, Protocol

from aenea_contracts import IncomingMessage, MessageKey


@dataclass(frozen=True, slots=True)
class AgentDescriptor:
    agent_id: str
    description: str
    trigger_phrases: tuple[str, ...]
    exclude_phrases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Route:
    status: Literal["matched", "unmatched", "ambiguous"]
    candidates: tuple[str, ...]

    @property
    def agent_id(self) -> str | None:
        return self.candidates[0] if self.status == "matched" else None


@dataclass(frozen=True, slots=True)
class Card:
    title: str
    summary: str


@dataclass(frozen=True, slots=True)
class IgnoreAction:
    reason: str
    kind: Literal["ignore"] = "ignore"


@dataclass(frozen=True, slots=True)
class AgentResult:
    card: Card
    action: IgnoreAction


class Agent(Protocol):
    descriptor: AgentDescriptor

    def handle(self, message: IncomingMessage) -> AgentResult: ...


@dataclass(frozen=True, slots=True)
class ActionReceipt:
    status: Literal["ignored"]
    reason: str


@dataclass(frozen=True, slots=True)
class Dispatch:
    key: MessageKey
    route: Route
    result: AgentResult | None = None
    receipt: ActionReceipt | None = None

    def to_dict(self) -> dict:
        return asdict(self)
