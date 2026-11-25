"""Read-only domain operations and per-run evidence for validating model output."""

from dataclasses import dataclass, field

from .catalog import Catalog, CatalogError, MasteriesProvider, MasteryBuild


@dataclass(repr=False)
class ToolContext:
    catalog: Catalog
    masteries: MasteriesProvider
    discovered_ids: set[str] = field(default_factory=set)
    observed_builds: dict[tuple[str, str], MasteryBuild] = field(default_factory=dict)

    async def search_characters(self, query: str) -> list[dict]:
        found = await self.catalog.search(query, limit=5)
        self.discovered_ids.update(character.character_id for character in found)
        return [
            {
                "character_id": character.character_id,
                "name": character.name,
                "names": character.names,
            }
            for character in found
        ]

    async def get_masteries(self, character_id: str) -> list[dict]:
        if character_id not in self.discovered_ids:
            raise CatalogError("Character must be discovered by search_characters first")
        builds = await self.masteries.get_masteries(character_id)
        if any(build.character_id != character_id for build in builds):
            raise CatalogError("Adapter returned a build for another character")
        for build in builds:
            key = (character_id, build.build_id)
            if key in self.observed_builds and self.observed_builds[key] != build:
                raise CatalogError("Adapter returned conflicting build IDs")
            self.observed_builds[key] = build
        return [
            {
                "character_id": build.character_id,
                "build_id": build.build_id,
                "label": build.label,
                "fixture": build.fixture,
            }
            for build in builds
        ]
