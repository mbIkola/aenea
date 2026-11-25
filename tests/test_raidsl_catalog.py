import unittest

from aenea_raidsl.catalog import CatalogError, Character, MemoryCatalog, load_fixture_services
from aenea_raidsl.tools import ToolContext


class CatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_id_and_name_are_required_translations_are_optional(self):
        catalog = MemoryCatalog([Character("alure", "Alure")])
        self.assertEqual((await catalog.search("ALURE"))[0].character_id, "alure")
        self.assertEqual((await catalog.get("alure")).names, {})
        self.assertEqual(await catalog.search("unknown"), ())

    async def test_optional_aliases_and_translations_are_searchable_and_bounded(self):
        catalog = MemoryCatalog(
            [
                Character("alure", "Alure", names={"ru": "Аллюра"}, aliases=("алюра",)),
                Character("alure_alt", "Alure Alt"),
            ]
        )
        self.assertEqual((await catalog.search("алюра"))[0].character_id, "alure")
        self.assertEqual((await catalog.search("Аллюра"))[0].character_id, "alure")
        self.assertEqual(len(await catalog.search("alure", limit=1)), 1)
        with self.assertRaises(ValueError):
            await catalog.search("", limit=0)

    async def test_duplicate_ids_and_unknown_ids_fail_explicitly(self):
        with self.assertRaises(CatalogError):
            MemoryCatalog([Character("x", "One"), Character("x", "Two")])
        with self.assertRaises(CatalogError):
            await MemoryCatalog([]).get("missing")

    async def test_tools_require_discovery_before_masteries_and_track_real_results(self):
        catalog, masteries = load_fixture_services()
        context = ToolContext(catalog, masteries)
        with self.assertRaises(CatalogError):
            await context.get_masteries("alure")
        found = await context.search_characters("Alure")
        self.assertEqual(found[0]["character_id"], "alure")
        builds = await context.get_masteries("alure")
        self.assertTrue(builds[0]["fixture"])
        self.assertNotIn("asset_ref", builds[0])
        self.assertIn(("alure", builds[0]["build_id"]), context.observed_builds)

    async def test_search_does_not_dump_full_catalog_or_local_paths_to_model(self):
        catalog = MemoryCatalog(
            [
                Character(str(index), f"Champion {index}", images={"art": "file:///private/art"})
                for index in range(1001)
            ]
        )
        _, masteries = load_fixture_services()
        context = ToolContext(catalog, masteries)
        found = await context.search_characters("Champion")
        self.assertLessEqual(len(found), 5)
        self.assertNotIn("file:///", str(found))
