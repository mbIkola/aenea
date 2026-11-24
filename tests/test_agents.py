import unittest
from dataclasses import replace

from aenea_agents import AgentDescriptor, AgentHub, Dispatcher, IgnoreWriter, Router
from aenea_agents.raidsl import RaidSLAgent
from test_inbox import message


class CountingAgent(RaidSLAgent):
    def __init__(self, descriptor=None):
        self.descriptor = descriptor or RaidSLAgent.descriptor
        self.calls = 0

    def handle(self, item):
        self.calls += 1
        return super().handle(item)


class AgentRoutingTests(unittest.TestCase):
    def test_routes_by_descriptor_and_invokes_only_selected_agent(self):
        raid = CountingAgent()
        auto = CountingAgent(AgentDescriptor("auto", "Авто", ("не заводится",)))
        hub = AgentHub([raid, auto])
        result = Dispatcher(hub).dispatch(message(text="Йо, ДАЙТЕ   ТАЛАНТЫ на Аллюру"))
        self.assertEqual(result.route.status, "matched")
        self.assertEqual(result.route.agent_id, "raidsl")
        self.assertEqual(raid.calls, 1)
        self.assertEqual(auto.calls, 0)
        self.assertEqual(result.result.card.summary, "Это моё, но пока игнорируем.")
        self.assertEqual(result.result.action.kind, "ignore")
        self.assertEqual(result.receipt.status, "ignored")

    def test_unmatched_message_does_not_invoke_any_agent(self):
        agent = CountingAgent()
        result = Dispatcher(AgentHub([agent])).dispatch(message(text="Всем добрый вечер"))
        self.assertEqual(result.route.status, "unmatched")
        self.assertIsNone(result.result)
        self.assertIsNone(result.receipt)
        self.assertEqual(agent.calls, 0)

    def test_ambiguity_is_explicit_and_registration_order_never_picks_a_winner(self):
        first = CountingAgent()
        second = CountingAgent(replace(first.descriptor, agent_id="another"))
        for agents in ([first, second], [second, first]):
            result = Dispatcher(AgentHub(agents)).dispatch(message(text="дайте таланты на героя"))
            self.assertEqual(result.route.status, "ambiguous")
            self.assertEqual(result.route.candidates, ("another", "raidsl"))
            self.assertIsNone(result.result)
        self.assertEqual(first.calls + second.calls, 0)

    def test_registration_rejects_duplicate_id_and_empty_trigger(self):
        agent = RaidSLAgent()
        with self.assertRaises(ValueError):
            AgentHub([agent, agent])
        invalid = CountingAgent(AgentDescriptor("bad", "Bad", ("   ",)))
        with self.assertRaises(ValueError):
            AgentHub([invalid])

    def test_phrase_boundaries_exclusions_and_whitespace(self):
        agent = CountingAgent(AgentDescriptor("example", "Example", ("таланты на",), ("продаю",)))
        router = Router(AgentHub([agent]))
        self.assertEqual(router.route(message(text="ТАЛАНТЫ\nНА героя")).status, "matched")
        self.assertEqual(router.route(message(text="таланты находятся тут")).status, "unmatched")
        self.assertEqual(router.route(message(text="продаю таланты на героя")).status, "unmatched")
        self.assertEqual(router.route(message(text="")).status, "unmatched")

    def test_writer_rejects_unknown_actions_without_external_effects(self):
        with self.assertRaises(TypeError):
            IgnoreWriter().execute(object())

    def test_result_contains_source_key_but_not_message_text_or_metadata(self):
        result = Dispatcher(AgentHub([RaidSLAgent()])).dispatch(
            message(text="дайте таланты на private-name", metadata_json='{"private":true}')
        )
        import json

        payload = json.dumps(result.to_dict(), ensure_ascii=False)
        self.assertNotIn("private-name", payload)
        self.assertNotIn("metadata", payload)
        self.assertEqual(result.to_dict()["key"]["message_id"], 33)
