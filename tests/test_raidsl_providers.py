import json
import unittest

import httpx2
from aenea_raidsl.agent import RaidSLAgent
from aenea_raidsl.catalog import load_fixture_services
from aenea_raidsl.config import load_model_config
from aenea_raidsl.provider import make_model
from aenea_raidsl.runtime_tools import FixtureTools
from openai import AsyncOpenAI
from test_raidsl_config import settings
from test_raidsl_runner import script


class ProviderProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_protocols_complete_real_sdk_tool_loop_over_mock_http(self):
        for provider in ("openai", "packet"):
            with self.subTest(provider=provider):
                config = load_model_config(settings(provider))
                requests = []
                outputs = script()

                def handler(request, outputs=outputs, requests=requests, provider=provider):
                    body = json.loads(request.content)
                    self.assertEqual(request.headers["authorization"], "Bearer synthetic-test-key")
                    self.assertEqual(body["model"], "test-model")
                    output = outputs[len(requests)]
                    requests.append((str(request.url), body))
                    if provider == "openai":
                        response = {
                            "id": f"resp_{len(requests)}",
                            "object": "response",
                            "created_at": 0,
                            "status": "completed",
                            "model": "test-model",
                            "error": None,
                            "output": [output.model_dump()],
                            "incomplete_details": None,
                            "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                        }
                    else:
                        message = {"role": "assistant", "content": None}
                        if output.type == "function_call":
                            message["tool_calls"] = [
                                {
                                    "id": output.call_id,
                                    "type": "function",
                                    "function": {
                                        "name": output.name,
                                        "arguments": output.arguments,
                                    },
                                }
                            ]
                            finish = "tool_calls"
                        else:
                            message["content"] = output.content[0].text
                            finish = "stop"
                        response = {
                            "id": f"chat_{len(requests)}",
                            "object": "chat.completion",
                            "created": 0,
                            "model": "test-model",
                            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                            "usage": {
                                "prompt_tokens": 10,
                                "completion_tokens": 5,
                                "total_tokens": 15,
                            },
                        }
                    return httpx2.Response(200, json=response)

                async with httpx2.AsyncClient(
                    transport=httpx2.MockTransport(handler),
                    trust_env=False,
                ) as http_client:
                    async with AsyncOpenAI(
                        api_key=config.api_key,
                        base_url=config.base_url,
                        http_client=http_client,
                        max_retries=0,
                    ) as client:
                        result = await RaidSLAgent(
                            config, FixtureTools(*load_fixture_services())
                        ).run(
                            "synthetic",
                            model=make_model(config, client),
                        )
                self.assertEqual(result.status, "ready")
                self.assertEqual(len(requests), 3)
                suffix = "/responses" if provider == "openai" else "/chat/completions"
                self.assertTrue(all(url == config.base_url + suffix for url, _ in requests))
                self.assertNotIn("response_format", requests[0][1])
                self.assertIn("search_characters", json.dumps(requests[0][1]["tools"]))
