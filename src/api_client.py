from __future__ import annotations

import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI


@dataclass
class CompletionResult:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    elapsed_seconds: float = 0.0


class APIClient:
    """Small OpenAI-compatible client that never logs the API key."""

    def __init__(
        self,
        base_url: str,
        model: str,
        key_file: str,
        temperature: float = 0.0,
        max_tokens: int = 8192,
        transport_retries: int = 3,
        thinking_mode: str = "disabled",
        request_timeout: float = 300.0,
    ) -> None:
        api_key = Path(key_file).read_text(encoding="utf-8").strip()
        if not api_key:
            raise ValueError(f"API key file is empty: {key_file}")
        self.client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=request_timeout,
            max_retries=0,
        )
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.transport_retries = transport_retries
        self.thinking_mode = thinking_mode

    def complete(
        self,
        system: str,
        user: str,
        history: Optional[List[Dict[str, str]]] = None,
        json_mode: bool = False,
    ) -> CompletionResult:
        messages: List[Dict[str, str]] = [{"role": "system", "content": system}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user})

        last_error: Optional[Exception] = None
        for attempt in range(self.transport_retries + 1):
            try:
                started = time.time()
                request: Dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self.temperature,
                    "max_tokens": self.max_tokens,
                }
                if json_mode:
                    request["response_format"] = {"type": "json_object"}
                if self.thinking_mode != "default":
                    request["extra_body"] = {"thinking": {"type": self.thinking_mode}}
                response = self.client.chat.completions.create(**request)
                usage: Any = getattr(response, "usage", None)
                return CompletionResult(
                    text=response.choices[0].message.content or "",
                    prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                    elapsed_seconds=round(time.time() - started, 3),
                )
            except Exception as exc:  # provider-specific transport failures
                last_error = exc
                if attempt >= self.transport_retries:
                    break
                time.sleep(min(8.0, (2**attempt) + random.random()))
        raise RuntimeError(f"API request failed after transport retries: {last_error}")

