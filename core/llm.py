"""LLM factory + JSON helper.

Wraps an OpenAI-compatible endpoint (GreenNode MaaS: Gemma / Qwen) via
``langchain_openai.ChatOpenAI``. Kept tiny so use cases just call ``complete``
or ``complete_json`` without knowing the provider.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional


class LLM:
    def __init__(self, model: str, base_url: str, api_key: str, temperature: float = 0.0):
        from langchain_openai import ChatOpenAI

        self._model = model
        # Qwen3 emits long internal reasoning by default; the /no_think directive
        # disables it (~3x faster, verified) and returns clean JSON. No-op elsewhere.
        self._no_think = "qwen" in model.lower()
        self._chat = ChatOpenAI(
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temperature,
            timeout=50,       # fail fast on a slow MaaS call; callers degrade gracefully
            max_retries=0,
        )

    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        if self._no_think:
            prompt = f"{prompt}\n/no_think"
        messages = []
        if system:
            messages.append(("system", system))
        messages.append(("user", prompt))
        return self._chat.invoke(messages).content

    def complete_json(self, prompt: str, system: Optional[str] = None) -> dict | list:
        """Ask for JSON and parse it, tolerating ```json fences / surrounding prose."""
        raw = self.complete(prompt, system=system)
        return _extract_json(raw)


def _extract_json(text: str) -> dict | list:
    text = text.strip()
    # Strip reasoning blocks some models (e.g. Qwen) emit before the answer.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Scan for the first balanced {...} / [...] block that parses (tolerates
    # surrounding prose or an unclosed reasoning prefix with stray braces).
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        while start != -1:
            depth = 0
            for i in range(start, len(text)):
                if text[i] == opener:
                    depth += 1
                elif text[i] == closer:
                    depth -= 1
                    if depth == 0:
                        try:
                            return json.loads(text[start : i + 1])
                        except json.JSONDecodeError:
                            break
            start = text.find(opener, start + 1)
    raise json.JSONDecodeError("no JSON object found in LLM output", text, 0)


def make_llm(temperature: float = 0.0, model: Optional[str] = None) -> LLM:
    # All MaaS models share one OpenAI-compatible endpoint + key — only `model`
    # differs, so an explicit `model` lets callers mix models on the same creds.
    model = model or os.environ.get("LLM_MODEL", "")
    base_url = os.environ.get("LLM_BASE_URL", "")
    api_key = os.environ.get("LLM_API_KEY", "")
    if not (model and base_url and api_key):
        raise ValueError(
            "LLM_MODEL, LLM_BASE_URL, LLM_API_KEY are required. "
            "Use /agentbase-llm to provision a GreenNode MaaS key."
        )
    return LLM(model=model, base_url=base_url, api_key=api_key, temperature=temperature)
