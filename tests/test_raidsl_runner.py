import asyncio
import json
import unittest

from aenea_raidsl.agent import RaidSLAgent, RaidSLRunError
from aenea_raidsl.catalog import load_fixture_services
from aenea_raidsl.config import load_model_config
from aenea_raidsl.runtime_tools import FixtureTools
from agents import Model
from agents.models.interface import ModelResponse
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)
from test_raidsl_config import settings


def call(name, arguments, call_id):
    return ResponseFunctionToolCall(
        id=f"fc_{call_id}",
        call_id=call_id,
        type="function_call",
        name=name,
        arguments=json.dumps(arguments),
        status="completed",
    )


def final(**overrides):
    payload = {
        "status": "ready",
        "character_id": "alure",
        "build_id": "fixture-demo",
        "reply": "Подготовлен тестовый ответ.",
    }
    payload.update(overrides)
    return ResponseOutputMessage(
        id="msg_final",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=json.dumps(payload), annotations=[])],
    )


class ScriptedModel(Model):
    def __init__(self, outputs):
        self.outputs = outputs
        self.inputs = []
        self.tracing_disabled = []

    async def get_response(self, *args, **kwargs):
        self.inputs.append(kwargs["input"])
        self.tracing_disabled.append(kwargs["tracing"].is_disabled())
        output = self.outputs[len(self.inputs) - 1]
        return ModelResponse(
            [output],
            Usage(requests=1, input_tokens=10, output_tokens=5, total_tokens=15),
            f"response_{len(self.inputs)}",
        )

    async def stream_response(self, *args, **kwargs):
        raise NotImplementedError
        yield


def script():
    return [
        call("search_characters", {"query": "Alure"}, "search"),
        call("get_masteries", {"character_id": "alure"}, "masteries"),
        final(),
    ]


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def agent(self, **overrides):
        return RaidSLAgent(
            load_model_config(settings(**overrides)), FixtureTools(*load_fixture_services())
        )

    async def test_real_sdk_executes_both_tools_then_validates_draft(self):
        model = ScriptedModel(script())
        result = await self.agent().run("Дайте таланты на Alure", model=model)
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.character_id, "alure")
        self.assertTrue(result.fixture)
        self.assertTrue(result.asset_ref.endswith("masteries-demo.svg"))
        self.assertEqual(result.usage["requests"], 3)
        self.assertTrue(all(model.tracing_disabled))
        self.assertIn("function_call_output", str(model.inputs[-1]))

    async def test_ready_without_tool_evidence_and_extra_paths_are_rejected(self):
        for outputs in (
            [final()],
            [*script()[:2], final(build_id="invented")],
            [*script()[:2], final(asset_ref="file:///etc/passwd")],
        ):
            with self.subTest(outputs=outputs):
                with self.assertRaises(RaidSLRunError):
                    await self.agent().run("synthetic", model=ScriptedModel(outputs))

    async def test_non_ready_result_never_contains_an_asset(self):
        result = await self.agent().run(
            "synthetic",
            model=ScriptedModel(
                [final(status="needs_clarification", character_id=None, build_id=None)]
            ),
        )
        self.assertEqual(result.status, "needs_clarification")
        self.assertIsNone(result.asset_ref)

    async def test_evidence_does_not_leak_between_runs(self):
        agent = self.agent()
        await agent.run("synthetic", model=ScriptedModel(script()))
        with self.assertRaises(RaidSLRunError):
            await agent.run("synthetic", model=ScriptedModel([final()]))

    async def test_timeout_cancellation_and_turn_limit(self):
        entered = asyncio.Event()

        class SlowModel(ScriptedModel):
            async def get_response(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()

        with self.assertRaises(RaidSLRunError):
            await self.agent(RAIDSL_TIMEOUT_SECONDS="0.01").run("synthetic", model=SlowModel([]))
        with self.assertRaises(RaidSLRunError):
            await self.agent(RAIDSL_MAX_TURNS="1").run("synthetic", model=ScriptedModel(script()))
        entered.clear()
        task = asyncio.create_task(self.agent().run("synthetic", model=SlowModel([])))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_provider_error_does_not_expose_key_or_remote_payload(self):
        class FailingModel(ScriptedModel):
            async def get_response(self, *args, **kwargs):
                raise RuntimeError("synthetic-secret remote payload")

        with self.assertRaises(RaidSLRunError) as caught:
            await self.agent().run("synthetic", model=FailingModel([]))
        self.assertNotIn("synthetic-secret", str(caught.exception))
