"""Tests for the AI orchestration: message building and the tool loop.

No real network: we monkeypatch the low-level model call.
"""
import ai_brain


class TestBuildMessages:
    def test_structure_and_language_rule(self):
        history = [{"you": "hi", "bot": "hello"}]
        msgs = ai_brain.build_messages("how are you", history, system_prompt="P")
        assert msgs[0]["role"] == "system"
        assert "same language" in msgs[0]["content"]
        assert msgs[-1] == {"role": "user", "content": "how are you"}

    def test_history_is_replayed(self):
        history = [{"you": "q1", "bot": "a1"}]
        msgs = ai_brain.build_messages("q2", history)
        roles = [m["role"] for m in msgs]
        assert roles == ["system", "user", "assistant", "user"]

    def test_memories_injected(self):
        msgs = ai_brain.build_messages("hey", [], memories=["likes tea"])
        assert "likes tea" in msgs[0]["content"]


class TestRunWithTools:
    def test_calls_tool_then_returns_final_text(self, monkeypatch):
        # First model turn asks for a tool; second returns plain content.
        turns = [
            {"tool_calls": [{
                "id": "c1",
                "function": {"name": "calculate", "arguments": '{"expression": "2+2"}'},
            }]},
            {"content": "The answer is 4.", "tool_calls": []},
        ]
        monkeypatch.setattr(ai_brain, "_chat_with_tools", lambda m, s: turns.pop(0))

        seen = []

        def dispatch(name, args):
            seen.append((name, args))
            return "2+2 = 4"

        out = ai_brain.run_with_tools([], [], dispatch)
        assert out == "The answer is 4."
        assert seen == [("calculate", {"expression": "2+2"})]

    def test_returns_none_when_provider_unavailable(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "_chat_with_tools", lambda m, s: None)
        assert ai_brain.run_with_tools([], [], lambda n, a: "") is None

    def test_no_tool_call_returns_content_directly(self, monkeypatch):
        monkeypatch.setattr(
            ai_brain, "_chat_with_tools",
            lambda m, s: {"content": "just chatting", "tool_calls": []},
        )
        assert ai_brain.run_with_tools([], [], lambda n, a: "") == "just chatting"


class TestSummarize:
    def test_empty_history_returns_none(self):
        assert ai_brain.summarize([]) is None

    def test_uses_chat_once(self, monkeypatch):
        monkeypatch.setattr(ai_brain, "chat_once", lambda messages: "- name: Sam")
        out = ai_brain.summarize([{"you": "hi", "bot": "hey Sam"}])
        assert out == "- name: Sam"
