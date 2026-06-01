from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class LLMError(RuntimeError):
    pass


@dataclass
class OperatorProposal:
    name: str
    source: str
    scenario: str
    limitations: list[str]
    trigger_features: list[str]
    explanation_template: str
    raw_response: str = ""


class LLMClient(Protocol):
    def generate_operator(self, system_prompt: str, user_prompt: str) -> OperatorProposal:
        ...


def _extract_json(text: str) -> dict:
    stripped = text.strip()
    if stripped.startswith("```"):
        match = re.search(r"```(?:json)?\s*(.*?)```", stripped, flags=re.DOTALL | re.IGNORECASE)
        if match:
            stripped = match.group(1).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            return json.loads(stripped[start : end + 1])
        raise


def proposal_from_text(text: str) -> OperatorProposal:
    payload = _extract_json(text)
    required = ["name", "source", "scenario", "limitations", "trigger_features", "explanation_template"]
    missing = [key for key in required if key not in payload]
    if missing:
        raise LLMError(f"LLM response missing fields: {missing}")
    return OperatorProposal(
        name=str(payload["name"]),
        source=str(payload["source"]),
        scenario=str(payload["scenario"]),
        limitations=[str(item) for item in payload.get("limitations", [])],
        trigger_features=[str(item) for item in payload.get("trigger_features", [])],
        explanation_template=str(payload["explanation_template"]),
        raw_response=text,
    )


class ClaudeMessagesClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 3000,
        temperature: float = 0.2,
        timeout: int = 90,
    ) -> None:
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com").rstrip("/")
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.timeout = timeout
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set")

    def generate_operator(self, system_prompt: str, user_prompt: str) -> OperatorProposal:
        payload = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        request = urllib.request.Request(
            f"{self.base_url}/v1/messages",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "content-type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LLMError(f"Claude API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise LLMError(f"Claude API request failed: {exc}") from exc

        text_parts = []
        for item in body.get("content", []):
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))
        text = "\n".join(text_parts).strip()
        if not text:
            raise LLMError("Claude API returned no text content")
        return proposal_from_text(text)


class FixtureLLMClient:
    def __init__(self, response_text: str) -> None:
        self.response_text = response_text

    def generate_operator(self, system_prompt: str, user_prompt: str) -> OperatorProposal:
        return proposal_from_text(self.response_text)
