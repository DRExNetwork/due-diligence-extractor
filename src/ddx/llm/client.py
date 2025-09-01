#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    def __init__(self, provider: str = "openai", model: Optional[str] = None):
        self.provider = provider.lower()
        self.model = model or os.getenv("LLM_MODEL", "")
        if self.provider == "openai":
            self._init_openai()
        else:
            raise ValueError(f"Unsupported provider: {provider}")

    def _init_openai(self):
        try:
            from openai import OpenAI  # type: ignore
        except Exception as e:
            raise RuntimeError("openai Python package not installed. `pip install openai`") from e

        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set in .env or environment.")
        self._openai = OpenAI(api_key=api_key)

        if not self.model:
            self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    def chat(
        self, messages: List[Dict[str, str]], response_format: Optional[Dict[str, Any]] = None
    ) -> str:
        if self.provider == "openai":
            return self._chat_openai(messages, response_format)
        raise ValueError(f"Unsupported provider: {self.provider}")

    def _chat_openai(
        self, messages: List[Dict[str, str]], response_format: Optional[Dict[str, Any]]
    ) -> str:
        resp = self._openai.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.0,
            response_format=response_format or {"type": "text"},
        )
        return resp.choices[0].message.content

    def complete(self, prompt: str, **kwargs) -> str:
        if self.provider == "openai":
            from openai import OpenAI

            client = OpenAI()
            resp = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=kwargs.get("temperature", 0.0),
                max_tokens=kwargs.get("max_tokens", 500),
            )
            # Return the content in both branches
            return resp.choices[0].message.content.strip()
        raise NotImplementedError(f"No .complete() handler for provider={self.provider}")
