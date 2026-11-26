"""Composition and durable projection of the terminal dummy agent workflow."""

import json
from collections.abc import Callable

from aenea_agents import AgentHub, Dispatcher
from aenea_raidsl.dummy import DummyRaidSLAgent as RaidSLAgent

from .inbox import SQLiteInbox


def default_hub() -> AgentHub:
    return AgentHub([RaidSLAgent()])


class RoutingProcessor:
    def __init__(self, inbox: SQLiteInbox, dispatcher: Dispatcher, emit: Callable[[dict], None]):
        self.inbox = inbox
        self.dispatcher = dispatcher
        self.emit = emit

    def process_scope(self, source_account_id: int, chat_id: int) -> None:
        while batch := self.inbox.pending_dispatches(source_account_id, chat_id):
            for message in batch:
                result = self.dispatcher.dispatch(message)
                # Canonical JSON-compatible projection is also what the CLI emits.
                payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
                if self.inbox.record_dispatch(message.key, payload):
                    self.emit({"type": "agent_dispatch", "dispatch": payload})
