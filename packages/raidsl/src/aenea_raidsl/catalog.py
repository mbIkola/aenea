"""Internal catalogue ports. The external catalogue JSON contract is not fixed."""

import json
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Protocol


class CatalogError(ValueError):
    """The requested catalogue entity cannot be resolved safely."""


@dataclass(frozen=True, slots=True)
class Character:
    character_id: str
    name: str
    names: dict[str, str] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    images: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MasteryBuild:
    character_id: str
    build_id: str
    label: str
    asset_ref: str | None
    fixture: bool
    recommendation: dict | None = None


class Catalog(Protocol):
    async def search(self, query: str, *, limit: int = 5) -> tuple[Character, ...]: ...

    async def get(self, character_id: str) -> Character: ...


class MasteriesProvider(Protocol):
    async def get_masteries(self, character_id: str) -> tuple[MasteryBuild, ...]: ...


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


class MemoryCatalog:
    def __init__(self, characters: Iterable[Character]):
        self._characters: dict[str, Character] = {}
        for character in characters:
            if not character.character_id.strip() or not character.name.strip():
                raise CatalogError("Character ID and name are required")
            if character.character_id in self._characters:
                raise CatalogError("Duplicate character ID")
            self._characters[character.character_id] = character

    async def search(self, query: str, *, limit: int = 5) -> tuple[Character, ...]:
        if not 1 <= limit <= 20:
            raise ValueError("Search limit must be between 1 and 20")
        query = _normalize(query)
        if not query:
            return ()
        if len(query) > 200:
            raise CatalogError("Search query is too long")
        matches = []
        for character in self._characters.values():
            names = [character.name, *character.names.values(), *character.aliases]
            normalized = [_normalize(name) for name in names]
            if any(query in name for name in normalized):
                matches.append((query not in normalized, character.name, character))
        matches.sort(key=lambda item: (item[0], item[1], item[2].character_id))
        return tuple(item[2] for item in matches[:limit])

    async def get(self, character_id: str) -> Character:
        try:
            return self._characters[character_id]
        except KeyError:
            raise CatalogError("Unknown character ID") from None


class FixtureMasteries:
    """Explicit fixture implementation; no HellHades integration or game advice."""

    async def get_masteries(self, character_id: str) -> tuple[MasteryBuild, ...]:
        if character_id != "alure":
            return ()
        image = Path(str(files("aenea_raidsl").joinpath("fixtures/masteries-demo.svg")))
        return (
            MasteryBuild(
                "alure",
                "fixture-demo",
                "Тестовый билд, не игровые данные",
                image.resolve().as_uri(),
                True,
            ),
        )


def load_fixture_services() -> tuple[Catalog, MasteriesProvider]:
    """Load only our bundled fixture, not the future external catalogue format."""
    raw = json.loads(files("aenea_raidsl").joinpath("fixtures/catalog.json").read_text())
    return MemoryCatalog(Character(**item) for item in raw["characters"]), FixtureMasteries()
