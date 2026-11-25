"""Dummy RaidSL: declare interests, claim a message, and deliberately ignore it."""

from aenea_contracts import IncomingMessage

from .contracts import AgentDescriptor, AgentResult, Card, IgnoreAction


class RaidSLAgent:
    descriptor = AgentDescriptor(
        agent_id="raidsl",
        description="Запросы талантов RAID: Shadow Legends; dummy без игровой логики.",
        trigger_phrases=("дайте таланты", "подскажите таланты", "таланты на", "таланты для"),
    )

    def handle(self, message: IncomingMessage) -> AgentResult:
        return AgentResult(
            Card("RaidSL — запрос талантов", "Это моё, но пока игнорируем."),
            IgnoreAction("dummy_agent"),
        )
