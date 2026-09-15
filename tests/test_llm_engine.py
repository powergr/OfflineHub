"""
Tests LLMEngine's history-trimming logic against a fake tokenizer, not a
real model - _build_input_tokens and _read_context_length don't touch
onnxruntime_genai at all, so there's no need to load a multi-GB model just
to verify the trimming algorithm itself. The real model is exercised
separately, by hand, against Phi-3-mini (see plan.md / session notes).
"""

import json
import os
import threading
import time

import pytest

from core.llm_engine import LLMEngine, _FALLBACK_CONTEXT_LENGTH, _TicketQueue


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

    def create_stream(self):
        return _FakeTokenizerStream()


class _FakeTokenizerStream:
    def decode(self, token):
        return token  # fake tokens are already plain strings


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


# ── retrieval-augmented context (plan.md Phase 4, item 14) ──────────────────

def test_no_context_matches_plain_behavior():
    """context=[] or context=None must render byte-identical to omitting
    it entirely - callers that never pass context (or a chat with nothing
    installed to retrieve from) must see zero behavior change."""
    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 1000

    tokens_no_context = e._build_input_tokens("sys", [], "hello", effective_max_tokens=10)
    tokens_empty_context = e._build_input_tokens("sys", [], "hello", effective_max_tokens=10, context=[])
    assert "".join(tokens_no_context) == "".join(tokens_empty_context) == "syshello"


def test_context_snippet_is_included_in_the_system_prompt():
    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 1000

    context = [{"module_name": "Wikipedia", "title": "Photosynthesis", "snippet": "PLANTS_MAKE_FOOD"}]
    tokens = e._build_input_tokens("sys", [], "how do plants eat", effective_max_tokens=10, context=context)
    text = "".join(tokens)

    assert "PLANTS_MAKE_FOOD" in text
    assert "Photosynthesis" in text
    assert "Wikipedia" in text
    assert "sys" in text  # base system prompt is still present, not replaced


def test_context_is_dropped_before_history_when_over_budget():
    """Retrieved context is a "might help" supplement; real conversation
    history is what the student is actually relying on. When both can't
    fit, the excerpt must go first.

    Budget math (FakeTokenizer = 1 char/token, verified against the real
    _build_system_prompt output rather than guessed): with the huge
    snippet the full system+history+prompt is 427 chars; without context
    it's 25. context_length=361 with effective_max_tokens=5 gives a
    budget of 100 - well inside that gap, so this only passes if context
    actually gets dropped first."""
    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 361

    history = [{"role": "user", "content": "HISTORY_MARKER"}]
    context = [{"module_name": "M", "title": "T", "snippet": "S" * 100}]  # huge - won't fit
    tokens = e._build_input_tokens("sys", history, "question", effective_max_tokens=5, context=context)
    text = "".join(tokens)

    assert "HISTORY_MARKER" in text  # history survives
    assert "S" * 100 not in text     # oversized context excerpt was dropped
    assert "question" in text        # current prompt always survives


def test_multiple_context_items_dropped_least_relevant_first():
    """retrieve() returns best matches first, so when trimming is needed
    the LAST (weakest-match) item must go before the first (strongest).

    Budget math: both items together = 560 chars; the first item alone =
    319. context_length=661 with effective_max_tokens=5 gives a budget of
    400 - inside that gap, so the worst item must be dropped to fit."""
    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 661

    context = [
        {"module_name": "M", "title": "Best", "snippet": "BEST_MATCH"},
        {"module_name": "M", "title": "Worst", "snippet": "WORST_MATCH" * 20},  # forces trimming
    ]
    tokens = e._build_input_tokens("sys", [], "q", effective_max_tokens=5, context=context)
    text = "".join(tokens)

    assert "BEST_MATCH" in text
    assert "WORST_MATCH" not in text


def test_build_system_prompt_returns_base_unchanged_when_no_context():
    assert LLMEngine._build_system_prompt("base prompt", []) == "base prompt"


def test_build_system_prompt_instructs_model_to_ignore_irrelevant_excerpts():
    result = LLMEngine._build_system_prompt("base", [{"module_name": "M", "title": "T", "snippet": "S"}])
    assert "ignore" in result.lower()
    assert "base" in result


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


# ── _TicketQueue (chat queue-position feedback) ──────────────────────────────

def test_first_ticket_has_position_zero():
    q = _TicketQueue()
    ticket = q.take_ticket()
    assert q.position(ticket) == 0


def test_second_ticket_has_position_one_ahead():
    q = _TicketQueue()
    first = q.take_ticket()
    second = q.take_ticket()
    assert q.position(first) == 0
    assert q.position(second) == 1


def test_done_advances_the_queue():
    q = _TicketQueue()
    first = q.take_ticket()
    second = q.take_ticket()
    third = q.take_ticket()
    assert (q.position(first), q.position(second), q.position(third)) == (0, 1, 2)

    q.done()  # first ticket finishes
    assert (q.position(second), q.position(third)) == (0, 1)

    q.done()  # second ticket finishes
    assert q.position(third) == 0


def test_tickets_are_served_in_real_first_come_first_served_order():
    """Drives the queue with real threads (not just sequential calls) to
    confirm tickets are actually served in arrival order under real
    concurrency, not just when called one at a time from a single thread -
    this is the exact scenario multiple students hitting /api/chat at once
    produces."""
    q = _TicketQueue()
    order_taken = []
    order_served = []
    lock = threading.Lock()
    start = threading.Event()

    def worker(i):
        start.wait()
        ticket = q.take_ticket()
        with lock:
            order_taken.append((ticket, i))
        while q.position(ticket) > 0:
            time.sleep(0.01)
        with lock:
            order_served.append(ticket)
        time.sleep(0.02)  # simulate doing work while holding its turn
        q.done()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join(timeout=5)

    expected_order = sorted(t for t, _ in order_taken)
    assert order_served == expected_order  # served strictly in ticket order
    assert len(set(order_served)) == 6  # every ticket served exactly once


def test_position_reflects_tickets_ahead_not_total_tickets_taken():
    """A ticket's position must only count OTHER unfinished tickets ahead of
    it, not shrink/grow from unrelated later arrivals behind it."""
    q = _TicketQueue()
    first = q.take_ticket()
    second = q.take_ticket()
    assert q.position(second) == 1
    q.take_ticket()  # a third ticket arrives behind - must not affect second's position
    assert q.position(second) == 1


# ── generate_stream() end-to-end with a fake onnxruntime-genai layer ────────
# Exercises the ACTUAL generate_stream() method (not just _TicketQueue in
# isolation) under real thread concurrency, without needing a real multi-GB
# model - fakes stand in for og.Model/og.GeneratorParams/og.Generator only;
# the queueing, serialization, and chunk-yielding logic is all real.

class _FakeGenerator:
    def __init__(self, tokens):
        self._tokens = list(tokens)
        self._i = 0

    def append_tokens(self, tokens):
        pass

    def is_done(self):
        return self._i >= len(self._tokens)

    def generate_next_token(self):
        pass

    def get_next_tokens(self):
        tok = self._tokens[self._i]
        self._i += 1
        return [tok]


class _FakeGeneratorParams:
    def __init__(self, model):
        pass

    def set_search_options(self, **kwargs):
        pass


class _FakeOG:
    """Stands in for the `og` module (onnxruntime_genai) - each fake
    Generator yields the SAME fixed token list regardless of the real
    prompt, since these tests only care about ordering/queueing, not
    actual generated content."""

    def __init__(self, tokens_per_call):
        self._tokens_per_call = tokens_per_call

    def GeneratorParams(self, model):
        return _FakeGeneratorParams(model)

    def Generator(self, model, params):
        return _FakeGenerator(self._tokens_per_call)


def test_generate_stream_serializes_concurrent_callers_and_reports_queue_position(monkeypatch):
    """Two real threads call generate_stream() on the SAME engine at once.
    The second caller must see a "[queue] 1" chunk before any of its own
    generated tokens, and - the actual point of keeping this serialized at
    all - the two callers' real generated tokens must never interleave."""
    import core.llm_engine as llm_engine_module

    fake_og = _FakeOG(tokens_per_call=["A", "B", "C"])
    monkeypatch.setattr(llm_engine_module, "og", fake_og)

    e = LLMEngine(model_dir="unused")
    e._tokenizer = FakeTokenizer()
    e._context_length = 100_000
    e._model = object()  # load() is a no-op once _model is already set

    results = {}
    start_second = threading.Event()

    def first_caller():
        chunks = []
        for chunk in e.generate_stream("hello"):
            chunks.append(chunk)
            if chunk == "A":
                start_second.set()  # let the second caller take its ticket mid-generation
                time.sleep(0.05)    # hold the "turn" a bit so overlap would be visible if buggy
        results["first"] = chunks

    def second_caller():
        start_second.wait(timeout=5)
        results["second"] = list(e.generate_stream("hi again"))

    t1 = threading.Thread(target=first_caller)
    t2 = threading.Thread(target=second_caller)
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert results["first"] == ["A", "B", "C"]
    # the second caller must have been told it was queued behind one other
    # request, and only see its own real tokens after that
    assert results["second"][0] == "[queue] 1"
    assert results["second"][1:] == ["A", "B", "C"]
