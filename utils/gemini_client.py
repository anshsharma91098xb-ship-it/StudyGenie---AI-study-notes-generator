"""
gemini_client.py
Gemini API wrapper with a fast model-fallback layer.

Speed-related changes vs. the original:
  * Thinking is turned off where the model allows it (big latency saving for
    extraction/summarisation tasks that need no deep reasoning).
  * Dead models (404 / retired) are skipped immediately and remembered, so
    parallel calls don't keep re-trying them.
  * Only rate-limit / overload errors (429, 5xx) are retried, with a short
    backoff. Other errors fall through to the next model without sleeping.
  * generate_json() uses Gemini's native JSON mode + schema, which removes
    most malformed-JSON retries.
Thread-safe: calls can be made from a ThreadPoolExecutor.
"""

import json
import re
import threading
import time
from typing import Any, List, Optional

from google import genai
from google.genai import types

# Re-check https://ai.google.dev/gemini-api/docs/deprecations periodically.
DEFAULT_FALLBACK_MODELS = [
    "gemini-3.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
]


class GeminiGenerationError(RuntimeError):
    """Raised when every model in the fallback chain fails."""


def _is_retryable(err: Exception) -> bool:
    msg = str(err).lower()
    return any(k in msg for k in ("429", "503", "500", "overloaded", "unavailable",
                                  "resource_exhausted", "rate"))


def _is_dead_model(err: Exception) -> bool:
    msg = str(err).lower()
    return "404" in msg or "not found" in msg or "no longer available" in msg


class GeminiClient:
    def __init__(self, api_key: str, models: Optional[List[str]] = None):
        if not api_key or not api_key.strip():
            raise ValueError("A Gemini API key is required.")
        self._client = genai.Client(api_key=api_key.strip())
        self.models = list(models or DEFAULT_FALLBACK_MODELS)
        self.last_used_model: Optional[str] = None
        self._dead: set = set()             # models that returned 404
        self._no_thinking_cfg: set = set()  # models that reject the thinking setting
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def _config(self, model: str, temperature: float, json_schema: Any):
        kwargs = {"temperature": temperature}
        if json_schema is not None:
            kwargs["response_mime_type"] = "application/json"
            kwargs["response_schema"] = json_schema
        if model not in self._no_thinking_cfg:
            kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        return types.GenerateContentConfig(**kwargs)

    def generate(
        self,
        prompt: str,
        temperature: float = 0.4,
        json_schema: Any = None,
        max_retries_per_model: int = 2,
        retry_backoff_seconds: float = 1.5,
    ) -> str:
        errors: List[str] = []

        for model in self.models:
            if model in self._dead:
                continue
            last_err: Optional[Exception] = None
            attempt = 0
            while attempt < max_retries_per_model:
                try:
                    resp = self._client.models.generate_content(
                        model=model,
                        contents=prompt,
                        config=self._config(model, temperature, json_schema),
                    )
                    text = getattr(resp, "text", None)
                    if text and text.strip():
                        with self._lock:
                            self.last_used_model = model
                        return text.strip()
                    last_err = GeminiGenerationError("empty response")
                    attempt += 1
                except Exception as e:  # noqa: BLE001
                    last_err = e
                    msg = str(e).lower()
                    if "thinking" in msg and model not in self._no_thinking_cfg:
                        # Model rejects the thinking setting: retry the same
                        # model without it (does not count as an attempt).
                        self._no_thinking_cfg.add(model)
                        continue
                    if _is_dead_model(e):
                        self._dead.add(model)
                        break
                    if _is_retryable(e):
                        attempt += 1
                        if attempt < max_retries_per_model:
                            time.sleep(retry_backoff_seconds * attempt)
                        continue
                    break  # other errors: go straight to the next model
            errors.append(f"{model}: {last_err}")

        raise GeminiGenerationError(
            "All Gemini models in the fallback chain failed:\n- " + "\n- ".join(errors)
        )

    def generate_json(self, prompt: str, schema: Any, temperature: float = 0.4):
        """Generate with native JSON mode and return the parsed Python object."""
        raw = self.generate(prompt, temperature=temperature, json_schema=schema)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            cleaned = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.M).strip()
            m = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
            return json.loads(m.group(1) if m else cleaned)