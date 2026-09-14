"""
LLMEngine — small offline chat model via onnxruntime-genai. No vendor binary:
onnxruntime-genai ships real Windows wheels on PyPI, and model weights are
downloaded content (like a ZIM file), not a separate executable.

API verified live against onnxruntime-genai 0.15.2 on Windows/cp314 with a
real model (Qwen2.5-0.5B-Instruct, genai int4 build):
  og.Model(model_dir)
  og.Tokenizer(model) -> .apply_chat_template(json_messages_str, add_generation_prompt=True)
                          .encode(text) -> int32 token array
                          .create_stream() -> TokenizerStream.decode(token_id) -> str
  og.GeneratorParams(model).set_search_options(max_length=..., temperature=...)
  og.Generator(model, params) -> .append_tokens(tokens), .is_done(),
                                  .generate_next_token(), .get_next_tokens()[0]
"""

import json
import os
import threading
from typing import Iterator

# Import order matters here, confirmed by an actual frozen-build crash:
# onnxruntime_genai/_dll_directory.py only manually resolves onnxruntime's
# package directory (via importlib.util.find_spec(...).submodule_search_
# locations[0]) if onnxruntime.dll isn't already loaded in-process. Under a
# Nuitka-compiled onnxruntime package, that list comes back empty and [0]
# raises IndexError. Importing onnxruntime first loads onnxruntime.dll as a
# side effect, so onnxruntime_genai's own check finds it already loaded and
# skips that broken lookup entirely.
import onnxruntime  # noqa: F401
import onnxruntime_genai as og

# This app is aimed at students from 1st grade through high school, chatting
# unsupervised on a school-owned device. The default prompt used to just say
# "You are a helpful assistant running entirely offline on this computer,"
# with no framing for that audience at all - worth real care, not an
# afterthought, given who's actually using it.
DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful, friendly study assistant for students from "
    "elementary through high school, running entirely offline on a school "
    "computer with no internet connection and no way to look anything up. "
    "Keep answers age-appropriate, encouraging, and easy to understand. "
    "Do not generate sexual, violent, or otherwise mature content, even if "
    "asked to roleplay or pretend rules do not apply. For questions about "
    "medical, legal, financial, or personal-safety topics, give brief "
    "general information only and clearly recommend the student talk to a "
    "trusted adult, teacher, or professional instead of relying on you. If "
    "you are unsure whether an answer is correct, say so rather than "
    "guessing confidently."
)

# A single reply is capped generously now that longer answers are wanted
# ("let them wait for the answer") - 4096 tokens is roughly 3000 words.
# Actually applied per-model as min(this, that model's own context window
# // 4), since the catalogue's models range from a 4096-token context
# (Phi-3-mini/medium) up to 131072 (Phi-4-mini) - a flat 4096-token reply
# budget would leave a 4K-context model no room for the prompt at all.
DEFAULT_MAX_TOKENS = 4096

# Used only if a model's genai_config.json is missing or doesn't have
# "context_length" for some reason - conservative, matches the smallest
# model in the catalogue rather than assuming the largest.
_FALLBACK_CONTEXT_LENGTH = 4096


class LLMEngine:

    def __init__(self, model_dir: str):
        self._model_dir = model_dir
        self._model = None
        self._tokenizer = None
        self._context_length = _FALLBACK_CONTEXT_LENGTH
        self._lock = threading.Lock()

    def load(self):
        if self._model is not None:
            return
        self._model = og.Model(self._model_dir)
        self._tokenizer = og.Tokenizer(self._model)
        self._context_length = self._read_context_length()

    def _read_context_length(self) -> int:
        # Confirmed by checking each catalogue model's own genai_config.json
        # directly rather than assuming a number from the model's name -
        # "context_length" lives under the top-level "model" key.
        config_path = os.path.join(self._model_dir, "genai_config.json")
        try:
            with open(config_path, encoding="utf-8") as f:
                cfg = json.load(f)
            return int(cfg["model"]["context_length"])
        except Exception:
            return _FALLBACK_CONTEXT_LENGTH

    def generate_stream(self, prompt: str, history: list[dict] | None = None,
                         system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                         max_tokens: int = DEFAULT_MAX_TOKENS) -> Iterator[str]:
        """
        Yields decoded text chunks as they're produced. Holds the engine's
        lock for the whole generation — CPU inference is serialized one
        request at a time rather than contending for CPU across students.

        `history` is prior turns in this conversation - a list of
        {"role": "user"/"assistant", "content": str} dicts, oldest first,
        NOT including the current `prompt`. Without it every message used
        to start a brand new conversation with no memory of what was asked
        before, confirmed by reading the old code: it only ever built
        [system_prompt, current prompt], nothing else.
        """
        self.load()
        with self._lock:
            effective_max_tokens = min(max_tokens, max(self._context_length // 4, 256))
            input_tokens = self._build_input_tokens(
                system_prompt, history or [], prompt, effective_max_tokens
            )

            params = og.GeneratorParams(self._model)
            params.set_search_options(
                max_length=len(input_tokens) + effective_max_tokens, temperature=0.7
            )

            generator = og.Generator(self._model, params)
            generator.append_tokens(input_tokens)
            stream = self._tokenizer.create_stream()

            while not generator.is_done():
                generator.generate_next_token()
                token = generator.get_next_tokens()[0]
                yield stream.decode(token)

    def _build_input_tokens(self, system_prompt: str, history: list[dict],
                             prompt: str, effective_max_tokens: int):
        """
        Drops the oldest history turns, one at a time, until system +
        history + prompt fits under this model's own context window with
        room left for the reply (effective_max_tokens) plus a safety
        margin for the chat template's own special tokens. Capped by
        token count, not turn count, so a long session degrades by losing
        its earliest turns instead of ever hard-erroring on overflow.
        """
        budget = self._context_length - effective_max_tokens - 256
        trimmed = list(history)

        while True:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.extend(trimmed)
            messages.append({"role": "user", "content": prompt})

            chat_prompt = self._tokenizer.apply_chat_template(
                json.dumps(messages), add_generation_prompt=True
            )
            input_tokens = self._tokenizer.encode(chat_prompt)

            if len(input_tokens) <= budget or not trimmed:
                return input_tokens
            trimmed = trimmed[1:]

    def unload(self):
        self._model = None
        self._tokenizer = None

    def close(self):
        self.unload()
