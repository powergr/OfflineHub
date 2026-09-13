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

DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant running entirely offline on this computer."


class LLMEngine:

    def __init__(self, model_dir: str):
        self._model_dir = model_dir
        self._model = None
        self._tokenizer = None
        self._lock = threading.Lock()

    def load(self):
        if self._model is not None:
            return
        self._model = og.Model(self._model_dir)
        self._tokenizer = og.Tokenizer(self._model)

    def generate_stream(self, prompt: str, system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                         max_tokens: int = 512) -> Iterator[str]:
        """
        Yields decoded text chunks as they're produced. Holds the engine's
        lock for the whole generation — CPU inference is serialized one
        request at a time rather than contending for CPU across students.
        """
        self.load()
        with self._lock:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            chat_prompt = self._tokenizer.apply_chat_template(
                json.dumps(messages), add_generation_prompt=True
            )
            input_tokens = self._tokenizer.encode(chat_prompt)

            params = og.GeneratorParams(self._model)
            params.set_search_options(
                max_length=len(input_tokens) + max_tokens, temperature=0.7
            )

            generator = og.Generator(self._model, params)
            generator.append_tokens(input_tokens)
            stream = self._tokenizer.create_stream()

            while not generator.is_done():
                generator.generate_next_token()
                token = generator.get_next_tokens()[0]
                yield stream.decode(token)

    def unload(self):
        self._model = None
        self._tokenizer = None

    def close(self):
        self.unload()
