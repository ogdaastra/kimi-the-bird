"""Anthropic's published limits on structured-output schemas, checked locally.

Kimi asks Claude Haiku for replies in a fixed JSON shape (``output_config.format``).
The API compiles each shape into a grammar and refuses shapes that break its
rules. Checking the same rules here means a mistake in Kimi's code is caught by
the tests, by the offline mock Haiku, and by the client before any request is
sent, instead of surfacing as a stream of refused requests on your PC.

Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
(sections "JSON Schema limitations" and "Schema complexity limits").
"""

from __future__ import annotations

import json
from typing import Any, Iterable

# Explicit limits (combined across every strict schema in one request).
MAX_UNION_PARAMS = 16          # parameters using anyOf or a list of types
MAX_OPTIONAL_PARAMS = 24       # properties not listed in "required"
MAX_STRICT_TOOLS = 20

# Kimi keeps well inside the limits so a small change can't tip it over.
KIMI_UNION_BUDGET = 12
KIMI_OPTIONAL_BUDGET = 0       # Kimi's schemas list every property as required

UNSUPPORTED_KEYWORDS = ("minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
                        "minLength", "maxLength", "maxItems", "uniqueItems", "minProperties",
                        "maxProperties", "patternProperties", "if", "then", "else", "not")


def _walk(node: Any, path: str = "$", parent: str = ""):
    """Yield (path, node, key-of-parent) for every schema node, skipping property-name maps."""
    yield path, node, parent
    if isinstance(node, dict):
        for k, v in node.items():
            if parent != "properties" or isinstance(v, (dict, list)):
                yield from _walk(v, f"{path}.{k}", k)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]", parent)


def _schema_nodes(schema: Any):
    """Only nodes that are schemas (not the {name: schema} map under "properties")."""
    for path, node, parent in _walk(schema):
        if isinstance(node, dict) and parent not in ("properties", "$defs", "definitions", "enum", "const"):
            yield path, node


def counts(schema: dict) -> dict:
    """Union-typed and optional parameter counts for one schema."""
    unions = optional = 0
    for _path, node in _schema_nodes(schema):
        if "anyOf" in node or isinstance(node.get("type"), list):
            unions += 1
        props = node.get("properties")
        if isinstance(props, dict):
            required = set(node.get("required") or [])
            optional += sum(1 for name in props if name not in required)
    return {"unions": unions, "optional": optional}


def schema_problems(schemas: Iterable[dict], strict_tools: int = 0) -> list[str]:
    """Every way these schemas (sent together in one request) break Anthropic's rules."""
    schemas = list(schemas)
    problems: list[str] = []
    total_unions = total_optional = 0
    for n, schema in enumerate(schemas):
        c = counts(schema)
        total_unions += c["unions"]
        total_optional += c["optional"]
        for path, node in _schema_nodes(schema):
            is_object = node.get("type") == "object" or "properties" in node
            if is_object and node.get("additionalProperties", None) is not False:
                problems.append(f"schema {n}: {path} must set additionalProperties to false")
            for kw in UNSUPPORTED_KEYWORDS:
                if kw in node:
                    problems.append(f"schema {n}: {path} uses unsupported keyword '{kw}'")
            if "minItems" in node and node["minItems"] not in (0, 1):
                problems.append(f"schema {n}: {path} minItems must be 0 or 1")
            ref = node.get("$ref")
            if isinstance(ref, str) and not ref.startswith("#"):
                problems.append(f"schema {n}: {path} uses an external $ref")
            if isinstance(ref, str) and ref in ("#", "#/"):
                problems.append(f"schema {n}: {path} is recursive")
            if "enum" in node and any(isinstance(v, (dict, list)) for v in node["enum"]):
                problems.append(f"schema {n}: {path} has complex types inside an enum")
        try:
            json.dumps(schema)
        except (TypeError, ValueError):
            problems.append(f"schema {n}: is not plain JSON")
    if total_unions > MAX_UNION_PARAMS:
        problems.append(f"{total_unions} parameters use anyOf/type lists (Anthropic allows {MAX_UNION_PARAMS})")
    if total_optional > MAX_OPTIONAL_PARAMS:
        problems.append(f"{total_optional} optional parameters (Anthropic allows {MAX_OPTIONAL_PARAMS})")
    if strict_tools > MAX_STRICT_TOOLS:
        problems.append(f"{strict_tools} strict tools (Anthropic allows {MAX_STRICT_TOOLS})")
    return problems


def within_kimi_budget(schema: dict) -> list[str]:
    """Kimi's own, tighter headroom rules (used by the tests)."""
    c = counts(schema)
    out = []
    if c["unions"] > KIMI_UNION_BUDGET:
        out.append(f"{c['unions']} union-typed parameters; keep it at {KIMI_UNION_BUDGET} or fewer for headroom")
    if c["optional"] > KIMI_OPTIONAL_BUDGET:
        out.append(f"{c['optional']} optional parameters; Kimi lists every property as required")
    return out
