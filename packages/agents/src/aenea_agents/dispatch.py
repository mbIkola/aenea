"""The current pipeline has terminal ignore actions only, with no external effects."""

from aenea_contracts import IncomingMessage

from .contracts import ActionReceipt, Dispatch, IgnoreAction
from .hub import AgentHub
from .router import Router


class IgnoreWriter:
    def execute(self, action: IgnoreAction) -> ActionReceipt:
        if not isinstance(action, IgnoreAction):
            raise TypeError("Only IgnoreAction is supported; sending is not implemented")
        return ActionReceipt("ignored", action.reason)


class Dispatcher:
    def __init__(self, hub: AgentHub):
        self.hub = hub
        self.router = Router(hub)
        self.writer = IgnoreWriter()

    def dispatch(self, message: IncomingMessage) -> Dispatch:
        route = self.router.route(message)
        if route.agent_id is None:
            return Dispatch(message.key, route)
        result = self.hub.get(route.agent_id).handle(message)
        receipt = self.writer.execute(result.action)
        return Dispatch(message.key, route, result, receipt)
