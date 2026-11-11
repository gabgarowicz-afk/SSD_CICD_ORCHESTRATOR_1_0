from __future__ import annotations
import json
from types import SimpleNamespace

import httpx
import pytest
from ssd_ci.clients import ClaudeHTTPAuditor, OpenAIPatchGenerator


def test_claude_rest_contract_temperature_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    observed = {}

    def transport(request: httpx.Request) -> httpx.Response:
        observed["url"] = str(request.url)
        observed["headers"] = dict(request.headers)
        observed["payload"] = json.loads(request.content)
        return httpx.Response(200, json={
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"status":"PASS_CONSTRUCTION"}'}],
        })

    client = httpx.Client(transport=httpx.MockTransport(transport))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-real-key")
    auditor = ClaudeHTTPAuditor(model="claude-model-explicit", client=client)
    text = auditor.audit(system_prompt="SYSTEM", message_xml="<ssd_audit_request/>")
    assert text == '{"status":"PASS_CONSTRUCTION"}'
    assert observed["url"] == "https://api.anthropic.com/v1/messages"
    assert observed["payload"]["temperature"] == 0
    assert observed["payload"]["system"] == "SYSTEM"
    assert observed["payload"]["model"] == "claude-model-explicit"
    assert observed["headers"]["anthropic-version"] == "2026-10-21"
    assert "test-not-a-real-key" in observed["headers"]["authorization"]


def test_claude_truncated_output_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    client = httpx.Client(transport=httpx.MockTransport(lambda _r: httpx.Response(200, json={
        "stop_reason": "max_tokens", "content": [{"type": "text", "text": "{}"}],
    })))
    with pytest.raises(ValueError, match="complete report"):
        ClaudeHTTPAuditor(model="explicit", client=client).audit(system_prompt="x", message_xml="x")


def test_generator_request_contains_only_authorized_feedback() -> None:
    logged = {}

    class StubResponses:
        def create(self, **kwargs):
            logged.update(kwargs)
            return SimpleNamespace(output_text=json.dumps({"patch": [
                {"op": "replace", "path": "/0/turns/0/choices/a/0/label", "value": "X"}]}))

    generator = OpenAIPatchGenerator(model="explicit-gen", client=SimpleNamespace(responses=StubResponses()))
    feedback = {"generator_feedback": {"items": [{"finding_id": "F-001", "instruction": "Fix label"}]},
                "remediation": [{"finding_id": "F-001", "instruction": "Adjust label", "must_not": []}]}
    out = generator.propose_patch(feedback)
    assert len(out["patch"]) == 1
    assert logged["model"] == "explicit-gen"
    assert json.loads(logged["input"]) == feedback
    assert "scenario_json" not in logged["input"]
    assert "engine_report" not in logged["input"]


def test_generator_refuses_non_json() -> None:
    class StubResponses:
        def create(self, **kwargs):
            return SimpleNamespace(output_text="not-json")
    client = SimpleNamespace(responses=StubResponses())
    with pytest.raises(ValueError, match="strict JSON"):
        OpenAIPatchGenerator(model="explicit-gen", client=client).propose_patch({"generator_feedback": {}, "remediation": []})
