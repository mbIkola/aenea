"""Per-run SDK tools and evidence; data backends do not own the model runtime."""

from dataclasses import dataclass, field
from typing import Protocol

from agents import FunctionTool, function_tool

from .catalog import Catalog, MasteriesProvider, MasteryBuild
from .tools import ToolContext


@dataclass(repr=False)
class RunTools:
    tools: list[FunctionTool]
    observed_builds: dict[tuple[str, str], MasteryBuild] = field(default_factory=dict)


class ToolFactory(Protocol):
    def create(self) -> RunTools: ...


class FixtureTools:
    def __init__(self, catalog: Catalog, masteries: MasteriesProvider):
        self.catalog = catalog
        self.masteries = masteries

    def create(self) -> RunTools:
        context = ToolContext(self.catalog, self.masteries)

        @function_tool(failure_error_function=None)
        async def search_characters(query: str) -> list[dict]:
            """Search the known catalogue by a character name; returns at most 5 candidates."""
            return await context.search_characters(query)

        @function_tool(failure_error_function=None)
        async def get_masteries(character_id: str) -> list[dict]:
            """Get builds for a character ID returned by search_characters in this run."""
            return await context.get_masteries(character_id)

        return RunTools([search_characters, get_masteries], context.observed_builds)
