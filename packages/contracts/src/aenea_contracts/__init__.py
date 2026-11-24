"""Transport-independent contracts shared by Aenea applications."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass(frozen=True, slots=True)
class MessageKey:
    source: str
    source_account_id: int
    chat_id: int
    message_id: int


@dataclass(frozen=True, slots=True)
class IncomingMessage:
    source: str
    source_account_id: int
    chat_id: int
    message_id: int
    sender_id: int | None
    text: str
    sent_at: datetime
    received_at: datetime
    reply_to_message_id: int | None
    reply_to_peer_id: int | None
    topic_id: int | None
    metadata_version: int
    metadata_json: str

    @property
    def key(self) -> MessageKey:
        return MessageKey(self.source, self.source_account_id, self.chat_id, self.message_id)


@dataclass(frozen=True, slots=True)
class StoreResult:
    key: MessageKey
    status: Literal["stored", "duplicate"]


__all__ = ["IncomingMessage", "MessageKey", "StoreResult"]
