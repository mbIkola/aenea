"""Consume the externally configured create_catalog_tools factory and v1 JSON API."""

import importlib.util
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

from .catalog import CatalogError, MasteryBuild
from .config import ConfigurationError
from .runtime_tools import RunTools


class CatalogProtocolError(CatalogError):
    """An external tool violated the public catalogue contract."""


@dataclass(frozen=True, slots=True)
class CatalogCLISettings:
    catalog_dir: Path
    cli_path: Path
    factory_path: Path
    metadata_path: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "CatalogCLISettings":
        catalog = env.get("RAIDSL_CATALOG_DIR", "")
        cli = env.get("RAIDSL_CATALOG_CLI", "")
        if not catalog or not cli:
            raise ConfigurationError("Укажите RAIDSL_CATALOG_DIR и RAIDSL_CATALOG_CLI явно.")
        cli_path = Path(cli).expanduser().resolve()
        factory = env.get("RAIDSL_CATALOG_TOOLS", str(cli_path.with_name("agent_sdk_tools.py")))
        metadata = env.get("RAIDSL_CATALOG_METADATA")
        return cls(
            Path(catalog).expanduser().resolve(),
            cli_path,
            Path(factory).expanduser().resolve(),
            Path(metadata).expanduser().resolve() if metadata else None,
        )


class CatalogCLITools:
    def __init__(self, settings: CatalogCLISettings, *, factory: Callable | None = None):
        self.settings = settings
        schema = json.loads(
            files("aenea_raidsl").joinpath("schemas/catalog-v1.schema.json").read_text()
        )
        self._schema = schema
        self._validator = Draft202012Validator(schema, format_checker=FormatChecker())
        self._factory = factory or self._load_factory()

    def _load_factory(self) -> Callable:
        cfg = self.settings
        if (
            not cfg.catalog_dir.is_dir()
            or not cfg.cli_path.is_file()
            or not cfg.factory_path.is_file()
        ):
            raise ConfigurationError("Каталог, CLI или фабрика tools недоступны по заданным путям.")
        if cfg.metadata_path is not None and not cfg.metadata_path.is_file():
            raise ConfigurationError("Явно указанный metadata-файл не найден.")
        spec = importlib.util.spec_from_file_location(
            "aenea_external_catalog_tools", cfg.factory_path
        )
        if spec is None or spec.loader is None:
            raise ConfigurationError("Не удалось загрузить фабрику catalog tools.")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception:
            raise ConfigurationError(
                "Не удалось импортировать фабрику catalog tools; payload скрыт."
            ) from None
        factory = getattr(module, "create_catalog_tools", None)
        if not callable(factory):
            raise ConfigurationError("В модуле отсутствует create_catalog_tools.")
        return factory

    def validate(self, command: str, raw: str) -> dict:
        try:
            if len(raw.encode("utf-8")) > 1_048_576:
                raise ValueError
            value = json.loads(raw)
            if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
                raise ValueError
            if value["schema_version"] != 1:
                raise ValueError
            self._validator.validate(value)
            if value["ok"]:
                shape = {
                    "get_character": "character",
                    "search_characters": "search",
                    "get_masteries": "recommendations",
                }[command]
                schema = {"$ref": f"#/$defs/{shape}", "$defs": self._schema["$defs"]}
                Draft202012Validator(schema, format_checker=FormatChecker()).validate(value["data"])
            return value
        except (ValueError, TypeError, KeyError, ValidationError):
            raise CatalogProtocolError("Catalogue returned an invalid v1 response") from None

    def create(self) -> RunTools:
        cfg = self.settings
        tools = self._factory(
            catalog_dir=str(cfg.catalog_dir),
            cli_path=str(cfg.cli_path),
            metadata_path=str(cfg.metadata_path) if cfg.metadata_path else None,
        )
        if {tool.name for tool in tools} != {
            "get_character",
            "search_characters",
            "get_masteries",
        } or len(tools) != 3:
            raise CatalogProtocolError(
                "Catalogue factory must expose exactly three read-only tools"
            )
        run = RunTools(tools)
        for tool in tools:
            tool.on_invoke_tool = self._observe(tool.name, tool.on_invoke_tool, run)
            if tool.name == "search_characters":
                limit = tool.params_json_schema["properties"]["limit"]
                limit.update(minimum=1, maximum=5)
                if "default" in limit:
                    limit["default"] = 5
        return run

    def _observe(self, name: str, invoke: Callable, run: RunTools) -> Callable:
        async def observed(context, arguments: str):
            if name == "search_characters":
                params = json.loads(arguments)
                limit = params.get("limit", 5)
                if type(limit) is not int or not 1 <= limit <= 5:
                    return json.dumps(
                        {
                            "schema_version": 1,
                            "ok": False,
                            "error": {
                                "code": "INVALID_ARGUMENTS",
                                "message": "Search limit must be 1..5",
                                "details": {},
                            },
                        }
                    )
                params["limit"] = limit
                arguments = json.dumps(params)
            raw = await invoke(context, arguments)
            value = self.validate(name, raw)
            if value["ok"] and name == "get_masteries":
                data = value["data"]
                if (data["status"] in {"unvalidated", "no_recommendations"}) != (
                    not data["builds"]
                ):
                    raise CatalogProtocolError("Recommendation status contradicts validated builds")
                character_id = data["character"]["character_id"]
                staged = {}
                for build in data["builds"]:
                    definitions = data["masteries"]
                    ids = build["mastery_ids"]
                    if any(
                        key not in definitions or definitions[key]["mastery_id"] != key
                        for key in ids
                    ):
                        raise CatalogProtocolError(
                            "A build references unresolved mastery definitions"
                        )
                    payload = {
                        "character": data["character"],
                        "status": data["status"],
                        "source": data["source"],
                        "build": build,
                        "masteries": {key: definitions[key] for key in ids},
                        "warnings": data["warnings"],
                        "unvalidated_build_count": data["unvalidated_build_count"],
                    }
                    key = (character_id, build["build_id"])
                    if key in staged:
                        raise CatalogProtocolError("Duplicate build ID in catalogue response")
                    staged[key] = MasteryBuild(
                        character_id, build["build_id"], build["label"], None, False, payload
                    )
                run.observed_builds.update(staged)
            return raw

        return observed
