from testbooks_runner.tests.minimal import minimal_instance


def test_object_gets_only_required_properties():
    schema = {"type": "object", "properties": {"a": {"type": "string"}, "b": {"type": "number"}},
              "required": ["a"]}
    assert minimal_instance(schema) == {"a": ""}


def test_array_gets_min_items():
    assert minimal_instance({"type": "array", "items": {"type": "integer"}}) == []
    assert minimal_instance({"type": "array", "items": {"type": "integer"}, "minItems": 2}) == [0, 0]


def test_strings_numbers_booleans():
    assert minimal_instance({"type": "string", "enum": ["x", "y"]}) == "x"
    assert minimal_instance({"type": "string", "format": "date"}) == "1970-01-01"
    assert minimal_instance({"type": "string"}) == ""
    assert minimal_instance({"type": "number"}) == 0
    assert minimal_instance({"type": "boolean"}) is False


def test_any_of_takes_the_first_and_ref_resolves():
    schema = {"$defs": {"row": {"type": "object", "properties": {"d": {"type": "string", "format": "date"}},
                                "required": ["d"]}},
              "type": "object", "required": ["rows", "n"],
              "properties": {"rows": {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/row"}},
                             "n": {"anyOf": [{"type": "null"}, {"type": "number"}]}}}
    assert minimal_instance(schema) == {"rows": [{"d": "1970-01-01"}], "n": None}
