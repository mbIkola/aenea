import unittest
from unittest.mock import patch

from aenea_raidsl.config import ConfigurationError, load_model_config
from aenea_raidsl.provider import make_client


def settings(provider="openai", **overrides):
    env = {
        "AENEA_ENV": "dev",
        "RAIDSL_PROVIDER": provider,
        "RAIDSL_MODEL": "test-model",
        "RAIDSL_API_KEY": "synthetic-test-key",
    }
    env.update(overrides)
    return env


class ModelConfigTests(unittest.TestCase):
    def test_explicit_provider_selects_endpoint_and_protocol_without_fallback(self):
        for provider, base_url, protocol in (
            ("openai", "https://api.openai.com/v1", "responses"),
            ("packet", "https://api.packet.ai/v1", "chat_completions"),
        ):
            config = load_model_config(settings(provider))
            self.assertEqual(config.base_url, base_url)
            self.assertEqual(config.protocol, protocol)
            self.assertNotIn("synthetic-test-key", repr(config))

    def test_requires_project_profile_model_and_resolved_explicit_key(self):
        for overrides in (
            {"AENEA_ENV": "prod"},
            {"RAIDSL_PROVIDER": "unknown"},
            {"RAIDSL_MODEL": ""},
            {"RAIDSL_API_KEY": ""},
            {"RAIDSL_API_KEY": "pass://aenea/openai/api_key"},
            {"RAIDSL_BASE_URL": "https://attacker.invalid/v1"},
            {"RAIDSL_MAX_TURNS": "0"},
            {"RAIDSL_TIMEOUT_SECONDS": "nan"},
        ):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ConfigurationError):
                    load_model_config(settings(**overrides))
        with self.assertRaises(ConfigurationError):
            load_model_config({"OPENAI_API_KEY": "inherited-key"})


class ClientIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_client_does_not_inherit_another_project_or_org_headers(self):
        with patch.dict("os.environ", {"OPENAI_ORG_ID": "other-org", "OPENAI_PROJECT_ID": "other"}):
            async with make_client(load_model_config(settings("packet"))) as client:
                self.assertIsNone(client.organization)
                self.assertIsNone(client.project)
                self.assertEqual(client.max_retries, 0)
