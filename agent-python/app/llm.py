# -*- coding: utf-8 -*-
"""LLM 封装：OpenAI 兼容（DeepSeek/通义/Ollama）+ 结构化输出 + Mock 降级。"""
from __future__ import annotations

import json
import re
from typing import Optional

from . import config


class LLMClient:
    """轻封装：chat_json 走 JSON 输出，chat 走普通对话。"""

    def __init__(self):
        self._client = None
        self._model = config.LLM_MODEL

    def _get(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY or "none")
        return self._client

    def chat(self, system: str, user: str, temperature: Optional[float] = None) -> str:
        resp = self._get().chat.completions.create(
            model=self._model,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=temperature if temperature is not None else config.LLM_TEMPERATURE,
        )
        return resp.choices[0].message.content or ""

    def chat_json(self, system: str, user: str) -> dict:
        """要求模型返回 JSON；兼容不支持 json_mode 的模型（正则提取兜底）。"""
        content = self.chat(system + "\n只输出 JSON，不要输出任何解释。", user)
        return parse_json_loose(content)


def parse_json_loose(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
        raise ValueError(f"无法解析 JSON 输出: {text[:200]}")


_llm: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = LLMClient()
    return _llm
