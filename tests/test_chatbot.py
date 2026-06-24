"""Tests for the rule-based brain: intent detection, mood, names, calculator."""
import chatbot


class TestIntent:
    def test_greeting_fires_on_bare_hello(self):
        assert chatbot.get_intent("hello") == "greeting"

    def test_greeting_does_not_hijack_a_task(self):
        # "hello" appears inside a real request -> should fall through to AI.
        assert chatbot.get_intent("write code to say hello in rust") is None

    def test_long_emotional_message_starting_with_hi_is_not_greeting(self):
        msg = "hi, I had an awful day and I just want to cry right now"
        assert chatbot.get_intent(msg) is None

    def test_unknown_message_returns_none(self):
        assert chatbot.get_intent("quantum entanglement explained") is None


class TestMood:
    def test_detects_sadness(self):
        assert chatbot.detect_mood("I feel so sad and lonely today")

    def test_detects_period_discomfort(self):
        assert chatbot.detect_mood("ugh my cramps are killing me, on my period")

    def test_phrase_detection(self):
        assert chatbot.detect_mood("honestly this was the worst day")

    def test_neutral_message_is_not_moody(self):
        assert not chatbot.detect_mood("what's the weather in Paris?")

    def test_empty_is_not_moody(self):
        assert not chatbot.detect_mood("")


class TestName:
    def test_my_name_is(self):
        assert chatbot.detect_name("my name is aarohi") == "Aarohi"

    def test_call_me(self):
        assert chatbot.detect_name("call me sam") == "Sam"

    def test_rejects_verb_having(self):
        # "I'm having trouble" must NOT be read as the name "Having".
        assert chatbot.detect_name("I'm having a hard time") is None

    def test_no_name_present(self):
        assert chatbot.detect_name("what is the time") is None


class TestCalculator:
    def test_addition(self):
        assert "8" in chatbot.try_calculate("what is 5 + 3")

    def test_multiplication(self):
        assert "12" in chatbot.try_calculate("6 * 2")

    def test_no_math_returns_none(self):
        assert chatbot.try_calculate("tell me a joke") is None


class TestLooksLikeTask:
    def test_request_word(self):
        assert chatbot.looks_like_task("explain recursion to me")

    def test_request_phrase(self):
        assert chatbot.looks_like_task("how do i center a div")

    def test_plain_chitchat_is_not_a_task(self):
        assert not chatbot.looks_like_task("hey there")
