"""Route using agent passports, without asking every agent to analyze a message."""

import re

from aenea_contracts import IncomingMessage

from .contracts import Route
from .hub import AgentHub, normalize_text


def _contains(text: str, phrase: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(normalize_text(phrase)) + r"(?!\w)", text) is not None


class Router:
    def __init__(self, hub: AgentHub):
        self.hub = hub

    def route(self, message: IncomingMessage) -> Route:
        text = normalize_text(message.text)
        candidates = tuple(
            descriptor.agent_id
            for descriptor in self.hub.descriptors()
            if any(_contains(text, phrase) for phrase in descriptor.trigger_phrases)
            and not any(_contains(text, phrase) for phrase in descriptor.exclude_phrases)
        )
        if not candidates:
            return Route("unmatched", ())
        return Route("matched" if len(candidates) == 1 else "ambiguous", candidates)
