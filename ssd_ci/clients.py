"""Explicit, replaceable cloud boundaries. No API call occurs on import.

External credentials are read at call time, never stored in artifacts or logs.
"""
from __future__ import annotations
import json
import os
from typing import Protocol, Any
import httpx


class AuditorClient(Protocol):
    def audit(self, *, system_prompt: str, message_xml: str) -> str:
        """Return raw JSON text from Claude."""
        ...


class GeneratorClient(Protocol):
    def propose_patch(self, feedback: dict[str, Any]) -> dict[str, Any]:
        """Return JSON Patch proposal; input is feedback/remediation only."""
        ...


class ClaudeHTTPAuditor:
    """Direct Anthropic Messages REST implementation (no Anthropic SDK dependency)."""

    def __init__(self, *, model: str, version: str = "2026-10-21",
                 max_tokens: int = 16000, timeout: float = 180.0,
                 base_url: str = "https://api.anthropic.com",
                 client: httpx.Client | None = None) -> None:
        if not model:
            raise ValueError("Pin a concrete Claude model version")
        self.model = model
        self.version = version
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.base_url = base_url.rstrip("/")
        self.client = client

    def audit(self, *, system_prompt: str, message_xml: str) -> str:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY missing")
        headers = {"Authorization": f"Bearer {key}", "anthropic-version": self.version,
                   "content-type": "application/json"}
        body = {"model": self.model, "max_tokens": self.max_tokens,
                "temperature": 0, "system": system_prompt,
                "messages": [{"role": "user", "content": message_xml}]}
        with httpx.Client(timeout=self.timeout) if self.client is None else _NoClose(self.client) as cli:
            response = cli.post(f"{self.base_url}/v1/messages", json=body, headers=headers)
            response.raise_for_status()
            answer = response.json()
        if answer.get("stop_reason") != "end_turn":
            raise ValueError(f"Claude ended without complete report: {answer.get('stop_reason')}")
        blocks = answer.get("content")
        if not isinstance(blocks, list):
            raise ValueError("Claude response has no content list")
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        if not text.strip():
            raise ValueError("Claude response has no text JSON")
        return text


class _NoClose:
    def __init__(self, client: httpx.Client) -> None:
        self.client = client

    def __enter__(self) -> httpx.Client:
        return self.client

    def __exit__(self, *_: object) -> None:
        pass


class OpenAIPatchGenerator:
    """Generate restricted JSON-Patch proposals from *only* authorized feedback.

    The current scenario and entire auditor report MUST NOT be passed to this
    endpoint. Consequence: low-quality suggestions may require human review.
    """

    def __init__(self, *, model: str, client: Any = None) -> None:
        self.model = model
        self.client = client

    def propose_patch(self, feedback: dict[str, Any]) -> dict[str, Any]:
        if self.client is None:
            from openai import OpenAI
            self.client = OpenAI()  # reads OPENAI_API_KEY
        instructions = (
            "You are an SSD construction generator. The input contains ONLY audited "
            "generator_feedback and GENERATOR remediation instructions. Never infer access "
            "to the full scenario or engine. Return ONLY a JSON object of shape "
            "{'patch':[{'op':'replace'|'add','path':'/0/turns/...','value':any},...]}. "
            "Paths are RFC6901 escaped, rooted at a list of scenarios. Do not change "
            "engine code, identifiers, graph, validation_status, variable classification "
            "or hidden world/configuration. If safe repair is impossible return {'patch':[]}."
        )
        response = self.client.responses.create(
            model=self.model, instructions=instructions,
            input=json.dumps(feedback, ensure_ascii=False, sort_keys=True),
            max_output_tokens=3500,
        )
        text = str(response.output_text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("Generator did not return strict JSON") from exc
        if not isinstance(data, dict) or set(data) != {"patch"} or not isinstance(data["patch"], list):
            raise ValueError("Invalid patch response shape")
        return data
