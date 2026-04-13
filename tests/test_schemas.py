from __future__ import annotations

from liminal.service import (
    CHALLENGER_SCHEMA,
    CHECK_PLANNER_SCHEMA,
    GENERATOR_SCHEMA,
    TESTER_SCHEMA,
    VERIFIER_SCHEMA,
)


def test_object_schemas_with_properties_are_strict_and_exhaustive() -> None:
    schemas = {
        "GENERATOR_SCHEMA": GENERATOR_SCHEMA,
        "CHECK_PLANNER_SCHEMA": CHECK_PLANNER_SCHEMA,
        "TESTER_SCHEMA": TESTER_SCHEMA,
        "VERIFIER_SCHEMA": VERIFIER_SCHEMA,
        "CHALLENGER_SCHEMA": CHALLENGER_SCHEMA,
    }

    for schema_name, schema in schemas.items():
        for path, issue in _find_schema_issues(schema):
            raise AssertionError(f"{schema_name} at {path}: {issue}")


def _find_schema_issues(schema: object, path: str = "root") -> list[tuple[str, str]]:
    failures: list[tuple[str, str]] = []
    if isinstance(schema, dict):
        if schema.get("type") == "object" and "properties" in schema:
            if schema.get("additionalProperties") is not False:
                failures.append((path, "objects with properties must declare additionalProperties: false"))
            property_names = list(schema["properties"].keys())
            required = schema.get("required", [])
            missing = [key for key in property_names if key not in required]
            if missing:
                failures.append((path, f"missing required keys: {missing}"))
        for key, value in schema.items():
            failures.extend(_find_schema_issues(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, item in enumerate(schema):
            failures.extend(_find_schema_issues(item, f"{path}[{index}]"))
    return failures
