import json
import tempfile
import unittest
from pathlib import Path

from aenea_raidsl.agent import RaidSLAgent, RaidSLRunError
from aenea_raidsl.catalog_cli import CatalogCLISettings, CatalogCLITools, CatalogProtocolError
from aenea_raidsl.config import ConfigurationError, load_model_config
from agents import function_tool
from agents.tool_context import ToolContext
from test_raidsl_config import settings
from test_raidsl_runner import ScriptedModel, call, final


def character():
    return {
        "character_id": "raid:1030",
        "canonical_name": "Alure",
        "names": {"en": "Alure"},
        "aliases": [],
        "images": {"portrait": "file:///catalog/alure.webp"},
    }


def recommendations():
    return {
        "character": character(),
        "status": "partial",
        "source": {
            "provider": "hellhades",
            "url": "https://example.test/alure",
            "fetched_at": None,
        },
        "builds": [
            {
                "build_id": "pve-1",
                "mode": "pve",
                "label": "Dungeon",
                "validation": "validated",
                "mastery_ids": [str(i) for i in range(15)],
            }
        ],
        "masteries": {
            str(i): {
                "mastery_id": str(i),
                "name": f"Mastery {i}",
                "description": "Description",
                "tree": "offense",
                "tier": 1,
                "images": {},
            }
            for i in range(15)
        },
        "unvalidated_builds": [],
        "unvalidated_build_count": 1,
        "warnings": [
            {
                "code": "UNVALIDATED_SOURCE_BUILDS",
                "count": 1,
                "message": "Source selection failed",
                "build_ids": ["broken"],
            }
        ],
    }


class CatalogCLITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.settings = CatalogCLISettings(root, root / "raid-catalog", root / "agent_sdk_tools.py")
        self.payload = recommendations()

    async def asyncTearDown(self):
        self.temp.cleanup()

    def factory(self):
        payload = self.payload

        def tools(**kwargs):
            @function_tool
            async def get_character(character: str) -> str:
                return json.dumps(
                    {"schema_version": 1, "ok": True, "data": globals()["character"]()}
                )

            @function_tool
            async def search_characters(query: str = "", limit: int = 20, offset: int = 0) -> str:
                return json.dumps(
                    {
                        "schema_version": 1,
                        "ok": True,
                        "data": {
                            "items": [globals()["character"]()],
                            "limit": limit,
                            "offset": offset,
                            "total": 1,
                        },
                    }
                )

            @function_tool
            async def get_masteries(
                character: str, mode: str = "all", include_unvalidated: bool = False
            ) -> str:
                return json.dumps({"schema_version": 1, "ok": True, "data": payload})

            return [get_character, search_characters, get_masteries]

        return tools

    def backend(self):
        return CatalogCLITools(self.settings, factory=self.factory())

    async def test_sdk_ready_uses_validated_cli_data_without_inventing_a_mastery_image(self):
        model = ScriptedModel(
            [
                call("get_character", {"character": "Alure"}, "lookup"),
                call(
                    "get_masteries",
                    {"character": "raid:1030", "mode": "pve", "include_unvalidated": False},
                    "builds",
                ),
                final(character_id="raid:1030", build_id="pve-1"),
            ]
        )
        agent = RaidSLAgent(load_model_config(settings()), self.backend())
        draft = await agent.run("Alure, Dungeon, pve-1", model=model)
        self.assertIsNone(draft.asset_ref)
        self.assertFalse(draft.fixture)
        self.assertEqual(draft.recommendation["build"]["build_id"], "pve-1")
        self.assertEqual(len(draft.recommendation["masteries"]), 15)
        self.assertEqual(draft.recommendation["unvalidated_build_count"], 1)

    async def test_unvalidated_or_unresolved_definitions_never_become_observed_builds(self):
        for update in (
            {"masteries": {}},
            {"builds": [{**recommendations()["builds"][0], "validation": "unvalidated"}]},
        ):
            self.payload = {**recommendations(), **update}
            tools = self.backend().create()
            with self.assertRaises(CatalogProtocolError):
                await tools.tools[2].on_invoke_tool(
                    ToolContext(
                        context=None,
                        tool_name="get_masteries",
                        tool_call_id="test",
                        tool_arguments="{}",
                    ),
                    json.dumps({"character": "Alure"}),
                )
            self.assertEqual(tools.observed_builds, {})

    async def test_bad_envelope_schema_version_and_business_error_are_distinct(self):
        backend = self.backend()
        for response in (
            {"schema_version": 2, "ok": True, "data": character()},
            {"schema_version": 1, "ok": True, "data": {}},
            {"schema_version": True, "ok": True, "data": character()},
        ):
            with self.assertRaises(CatalogProtocolError):
                backend.validate("get_character", json.dumps(response))
        error = {
            "schema_version": 1,
            "ok": False,
            "error": {
                "code": "AMBIGUOUS_CHARACTER",
                "message": "Select an ID",
                "details": {"candidates": [{"character_id": "raid:1030"}]},
            },
        }
        self.assertEqual(backend.validate("get_character", json.dumps(error)), error)

    async def test_unobserved_result_rejected_and_search_limit_is_bounded(self):
        agent = RaidSLAgent(load_model_config(settings()), self.backend())
        with self.assertRaises(RaidSLRunError):
            await agent.run(
                "synthetic",
                model=ScriptedModel([final(character_id="raid:1030", build_id="pve-1")]),
            )
        run = self.backend().create()
        result = json.loads(
            await run.tools[1].on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="search_characters",
                    tool_call_id="test",
                    tool_arguments="{}",
                ),
                json.dumps({"query": "Alure", "limit": 100}),
            )
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "INVALID_ARGUMENTS")


class CatalogCLIConfigurationTests(unittest.TestCase):
    def test_factory_import_error_payload_is_hidden(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / "raid-catalog"
            cli.touch()
            factory = root / "agent_sdk_tools.py"
            factory.write_text("raise RuntimeError('synthetic-private-payload')")
            with self.assertRaises(ConfigurationError) as failure:
                CatalogCLITools(CatalogCLISettings(root, cli, factory))
            self.assertNotIn("synthetic-private-payload", str(failure.exception))
            self.assertIsNone(failure.exception.__cause__)

    def test_paths_are_explicit_and_missing_factory_does_not_fall_back(self):
        with self.assertRaises(ConfigurationError):
            CatalogCLISettings.from_env({})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = CatalogCLISettings.from_env(
                {
                    "RAIDSL_CATALOG_DIR": directory,
                    "RAIDSL_CATALOG_CLI": str(root / "raid-catalog"),
                }
            )
            self.assertEqual(settings.factory_path, root.resolve() / "agent_sdk_tools.py")
            with self.assertRaises(ConfigurationError):
                CatalogCLITools(settings)


class CatalogCLISubprocessTests(unittest.IsolatedAsyncioTestCase):
    async def test_load_factory_and_execute_json_cli_without_external_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cli = root / "read_cli.py"
            cli.write_text(
                "import json\nprint("
                + repr(json.dumps({"schema_version": 1, "ok": True, "data": character()}))
                + ")\n"
            )
            factory = root / "agent_sdk_tools.py"
            factory.write_text("""
import asyncio
import sys
from agents import function_tool

def create_catalog_tools(catalog_dir, cli_path, metadata_path=None):
    @function_tool
    async def get_character(character: str) -> str:
        process = await asyncio.create_subprocess_exec(
            sys.executable, cli_path, character, stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await process.communicate()
        return stdout.decode()
    @function_tool
    async def search_characters(query: str = '', limit: int = 20, offset: int = 0) -> str:
        return '{}'
    @function_tool
    async def get_masteries(
        character: str, mode: str = 'all', include_unvalidated: bool = False
    ) -> str:
        return '{}'
    return [get_character, search_characters, get_masteries]
""")
            backend = CatalogCLITools(CatalogCLISettings(root, cli, factory))
            run = backend.create()
            arguments = json.dumps({"character": "Alure"})
            raw = await run.tools[0].on_invoke_tool(
                ToolContext(
                    context=None,
                    tool_name="get_character",
                    tool_call_id="subprocess",
                    tool_arguments=arguments,
                ),
                arguments,
            )
            self.assertEqual(json.loads(raw)["data"]["character_id"], "raid:1030")
