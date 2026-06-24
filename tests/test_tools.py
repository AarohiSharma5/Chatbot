"""Tests for the built-in tools and their function-calling schemas."""
import tools


class TestCalculate:
    def test_simple(self):
        assert tools.calculate("12 * (3 + 4)") == "12 * (3 + 4) = 84"

    def test_integer_result_has_no_decimal(self):
        assert tools.calculate("10 / 2").endswith("= 5")

    def test_rejects_code_injection(self):
        # Anything that isn't plain arithmetic must fail safely, not execute.
        assert tools.calculate("__import__('os').system('echo hi')") == \
            "I couldn't evaluate that expression."

    def test_garbage_is_handled(self):
        assert "couldn't" in tools.calculate("not math at all")


class TestDatetime:
    def test_returns_sentence(self):
        out = tools.current_datetime()
        assert out.startswith("It is") and out.endswith(".")


class TestSchemas:
    def test_all_schemas_well_formed(self):
        names = set()
        for schema in tools.TOOL_SCHEMAS:
            assert schema["type"] == "function"
            fn = schema["function"]
            assert fn["name"] and fn["description"]
            assert fn["parameters"]["type"] == "object"
            names.add(fn["name"])
        # The five tools the user asked for must all be advertised.
        assert {"get_weather", "web_answer", "calculate",
                "current_datetime", "remember_fact"} <= names
