"""
Tests LLMEngine's history-trimming logic against a fake tokenizer, not a
real model - _build_input_tokens and _read_context_length don't touch
onnxruntime_genai at all, so there's no need to load a multi-GB model just
to verify the trimming algorithm itself. The real model is exercised
separately, by hand, against Phi-3-mini (see plan.md / session notes).
"""

import json
import os

import pytest

from core.llm_engine import LLMEngine, _FALLBACK_CONTEXT_LENGTH


class FakeTokenizer:
    """1 token per character, so test message lengths are easy to reason
    about exactly - real tokenizers are subword, but the trimming logic
    only cares about "how many tokens does encode() report," not what a
    token actually is."""

    def apply_chat_template(self, messages_json, add_generation_prompt=True):
        messages = json.loads(messages_json)
        return "".join(m["content"] for m in messages)

    def encode(self, text):
        return list(text)  # length == len(text), content unused


@pytest.fixture
def engine():
    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 100_000  # plenty of headroom - nothing should get trimmed
    return e


def test_no_trimming_needed_when_conversation_is_short(engine):
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
    tokens = engine._build_input_tokens("sys", history, "how are you", effective_max_tokens=10)
    assert "".join(tokens) == "syshihellohow are you"


def test_drops_oldest_turn_first_when_over_budget():
    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 40  # small, deliberately forces trimming

    history = [
        {"role": "user", "content": "A" * 10},        # oldest
        {"role": "assistant", "content": "B" * 10},
        {"role": "user", "content": "C" * 10},         # newest
        {"role": "assistant", "content": "D" * 10},
    ]
    tokens = e._build_input_tokens("", history, "E" * 5, effective_max_tokens=5)
    text = "".join(tokens)

    # budget = 40 - 5 - 256 -> clamps to nothing fitting except by dropping
    # turns; the newest turns and the current prompt must survive, the
    # oldest ("A"*10) must be the first to go.
    assert "E" * 5 in text  # current prompt always present
    assert "A" * 10 not in text or "D" * 10 in text  # oldest dropped before newest


def test_always_keeps_current_prompt_even_if_everything_else_dropped():
    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 1  # absurdly small - forces dropping all history

    history = [{"role": "user", "content": "X" * 500}, {"role": "assistant", "content": "Y" * 500}]
    tokens = e._build_input_tokens("system prompt here", history, "my question", effective_max_tokens=1)
    text = "".join(tokens)

    assert "my question" in text
    assert "X" * 500 not in text
    assert "Y" * 500 not in text


def test_no_history_matches_old_behavior():
    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 1000

    tokens = e._build_input_tokens("sys", [], "hello", effective_max_tokens=10)
    assert "".join(tokens) == "syshello"


def test_read_context_length_from_real_genai_config(tmp_path):
    (tmp_path / "genai_config.json").write_text(json.dumps({"model": {"context_length": 4096}}))
    e = LLMEngine(model_dir=str(tmp_path))
    assert e._read_context_length() == 4096


def test_read_context_length_falls_back_when_missing(tmp_path):
    e = LLMEngine(model_dir=str(tmp_path))  # no genai_config.json at all
    assert e._read_context_length() == _FALLBACK_CONTEXT_LENGTH


def test_read_context_length_falls_back_on_malformed_json(tmp_path):
    (tmp_path / "genai_config.json").write_text("{not valid json")
    e = LLMEngine(model_dir=str(tmp_path))
    assert e._read_context_length() == _FALLBACK_CONTEXT_LENGTH
