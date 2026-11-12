"""Every structured-output schema Kimi sends must stay within Anthropic's limits."""

import pytest

from kimi.ai.prompts import (
    MAX_UNION_PARAMS,
    decision_schema,
    image_schema,
    reflection_schema,
    research_schema,
    union_param_count,
)


@pytest.mark.parametrize("make", [decision_schema, research_schema, reflection_schema, image_schema])
def test_schemas_stay_under_the_union_parameter_limit(make):
    schema = make()
    # Anthropic refuses schemas with more than 16 nullable / union-typed parameters.
    assert union_param_count(schema) <= MAX_UNION_PARAMS == 16
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])


def test_decision_schema_leaves_room_to_grow():
    assert union_param_count(decision_schema()) <= 10


def test_union_counter_counts_anyof_and_type_lists():
    schema = {"properties": {"a": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                             "b": {"type": ["string", "null"]}, "c": {"type": "string"}}}
    assert union_param_count(schema) == 2
