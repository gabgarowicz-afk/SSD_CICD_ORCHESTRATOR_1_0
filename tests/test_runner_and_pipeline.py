from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ssd_ci.models import RunContext
from ssd_ci.orchestrator import Pipeline, PipelineConfig
from ssd_ci.runner import run_engine, hash_engine

from test_models_and_security import report

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "assets/scenarios/B2_GABINET_URZAD_MIGRACJE_KONSTRUKCYJNE.json"
ENGINE = ROOT / "assets/engine_ref"
SCHEMA = ROOT / "assets/schema/raport_audytu.schema.json"


class FakeAuditor:
    def __init__(self, statuses: list[str], invalid_first: bool = False) -> None:
        self.statuses = statuses
        self.calls = 0
        self.invalid_first = invalid_first

    def audit(self, *, system_prompt: str, message_xml: str) -> str:
        self.calls += 1
        if self.invalid_first and self.calls == 1:
            return "not json"
        root = ET.fromstring(message_xml)
        ctx = RunContext.model_validate(json.loads(root.find("run_context").text))
        status = self.statuses[min(self.calls - 1, len(self.statuses) - 1)]
        r = report(ctx, status=status)
        if status == "FAIL":
            r["checks"][0]["result"] = "FAIL"
            r["findings"] = [{
                "finding_id": "F-001", "invariant": "INV-01", "severity": "MAJOR",
                "basis": "STATIC_READING", "engine_error_code": None,
                "location": {"scenario_id": "B2-CLINIC", "json_path": "/0/turns/0/choices/doctor/0/label",
                             "rule_ids": [], "turn": 1, "phase": "definition", "actor": "doctor",
                             "configurations": [], "engine_file": None},
                "description": "Improve label", "evidence_excerpt": "n/a",
                "remediation": {"target": "GENERATOR", "instruction": "Change label",
                                "must_not": ["Do not change world"]},
            }]
            r["generator_feedback"] = {"allowed": True,
                                      "items": [{"finding_id": "F-001", "instruction": "Rename option"}]}
        return json.dumps(r, ensure_ascii=False)


class FakeGenerator:
    def __init__(self) -> None:
        self.feedback: list[dict[str, Any]] = []

    def propose_patch(self, feedback: dict[str, Any]) -> dict[str, Any]:
        self.feedback.append(feedback)
        return {"patch": [{"op": "replace", "path": "/0/turns/0/choices/doctor/0/label",
                           "value": "Zatrzymaj wysłanie wykazu (poprawione)"}]}


def cfg(tmp_path: Path, *, iterations: int = 3) -> PipelineConfig:
    prompt = tmp_path / "auditor_prompt.md"
    prompt.write_text('Testing only! No production Claude prompt attached. "report_version" "INV-16"', encoding="utf-8")
    return PipelineConfig(scenarios_path=SCENARIOS, engine_root=ENGINE,
                          engine_baseline_path=ENGINE / "BASELINE_ENGINE_SHA256.txt",
                          report_schema_path=SCHEMA, prompt_path=prompt,
                          output_dir=tmp_path / "out", max_iterations=iterations,
                          run_id="test", shuffles=(), regressions=())


def fake_runner(scenarios, engine_root, *, max_paths, shuffle_seeds, regression_scripts):
    return {"enumeration_complete": True, "errors": [], "has_engine_errors": False,
            "results": [], "regressions": {"ok": True}, "total_paths": 1, "total_shuffles": 0}


def test_actual_engine_full_enumeration_and_regression() -> None:
    scenarios = json.loads(SCENARIOS.read_text("utf-8"))
    r = run_engine(scenarios, ENGINE, shuffle_seeds=(1,), regression_scripts=("test_c0.py",))
    assert r["enumeration_complete"]
    assert r["total_paths"] == 108
    assert r["total_shuffles"] == 108
    assert r["errors"] == []
    assert r["regressions"]["ok"]


def test_auto_fix_feedback_only_then_pass(tmp_path: Path) -> None:
    audit = FakeAuditor(["FAIL", "PASS_CONSTRUCTION"])
    generator = FakeGenerator()
    result = Pipeline(cfg(tmp_path), audit, generator, runner=fake_runner).run()
    assert result["effective_status"] == "PASS_CONSTRUCTION"
    assert len(result["iterations"]) == 2
    assert set(generator.feedback[0]) == {"generator_feedback", "remediation"}
    assert len(generator.feedback[0]["remediation"]) == 1
    assert not result["engine_changed"]
    assert SCENARIOS.read_text("utf-8").find("poprawione") == -1  # source remains untouched


def test_invalid_response_one_retry_then_pass(tmp_path: Path) -> None:
    audit = FakeAuditor(["PASS_CONSTRUCTION", "PASS_CONSTRUCTION"], invalid_first=True)
    result = Pipeline(cfg(tmp_path), audit, runner=fake_runner).run()
    assert result["effective_status"] == "PASS_CONSTRUCTION"
    assert audit.calls == 2


def test_invalid_response_twice_escalates(tmp_path: Path) -> None:
    class BadAuditor:
        def audit(self, *, system_prompt: str, message_xml: str) -> str:
            return '{"broken":true}'
    result = Pipeline(cfg(tmp_path), BadAuditor(), runner=fake_runner).run()
    assert result["effective_status"] == "ESCALATE_HUMAN"
    assert result["reason"] == "AUDITOR_INVALID_AFTER_ONE_RETRY"


def test_engine_change_escalates_and_blocks_generator(tmp_path: Path) -> None:
    config = cfg(tmp_path)
    baseline = tmp_path / "untrusted_baseline.txt"
    baseline.write_text("f"*64, encoding="utf-8")
    config = PipelineConfig(**{**config.__dict__, "engine_baseline_path": baseline})
    aud = FakeAuditor(["PASS_CONSTRUCTION"])
    gen = FakeGenerator()
    result = Pipeline(config, aud, gen, runner=fake_runner).run()
    assert result["engine_changed"]
    assert result["effective_status"] == "ESCALATE_HUMAN"
    assert not gen.feedback


def test_iteration_limit_is_three_and_requires_human(tmp_path: Path) -> None:
    aud = FakeAuditor(["FAIL", "FAIL", "FAIL"])
    gen = FakeGenerator()
    result = Pipeline(cfg(tmp_path), aud, gen, runner=fake_runner).run()
    assert result["effective_status"] == "FAIL"
    assert result["human_escalation"] is True
    assert result["reason"] == "ITERATION_LIMIT_REQUIRES_HUMAN"
    assert len(result["iterations"]) == 3


def test_max_iterations_over_three_is_forbidden(tmp_path: Path) -> None:
    import pytest
    with pytest.raises(ValueError):
        cfg(tmp_path, iterations=4)


def test_b_step_matches_original_b_execute_across_108_paths() -> None:
    """Orchestrator's incremental adapter cannot silently change B2.2 semantics."""
    import importlib
    from ssd_ci.runner import _b_step, _digest_state, _b_menu, load_modules
    mods = load_modules(ENGINE)
    scenarios = json.loads(SCENARIOS.read_text("utf-8"))
    import itertools
    count = 0
    for sc in scenarios:
        grids = []
        for turn in sc["turns"]:
            actors = sorted(turn["choices"])
            grids.append([dict(zip(actors, v)) for v in itertools.product(
                *[[o["id"] for o in turn["choices"][actor]] for actor in actors])])
        for cfg in sc["configurations"]:
            for sequence in itertools.product(*grids):
                st = mods.b.initial(sc, cfg)
                for i, picks in enumerate(sequence):
                    st = _b_step(mods.b, sc, st, i, picks)
                original = mods.b.execute(sc, cfg, list(sequence))
                assert _digest_state(st) == _digest_state(original)
                count += 1
    assert count == 108


def test_max_paths_exceeded_does_not_silently_claim_completeness() -> None:
    scenarios = json.loads(SCENARIOS.read_text("utf-8"))
    r = run_engine(scenarios, ENGINE, max_paths=2, shuffle_seeds=(), regression_scripts=())
    assert not r["enumeration_complete"]
    assert any(e["code"] == "ENUMERATION_LIMIT_EXCEEDED" for e in r["errors"])


def test_changed_run_context_is_rejected_then_escalated(tmp_path: Path) -> None:
    class WrongContext:
        def audit(self, *, system_prompt: str, message_xml: str) -> str:
            root = ET.fromstring(message_xml)
            ctx = RunContext.model_validate(json.loads(root.find("run_context").text))
            data = report(ctx)
            data["run_context"]["run_id"] = "different-run"
            return json.dumps(data)
    r = Pipeline(cfg(tmp_path), WrongContext(), runner=fake_runner).run()
    assert r["reason"] == "AUDITOR_INVALID_AFTER_ONE_RETRY"
    assert r["effective_status"] == "ESCALATE_HUMAN"


def test_missing_prompt_file_fails_closed(tmp_path: Path) -> None:
    import pytest
    c = cfg(tmp_path)
    c.prompt_path.unlink()
    with pytest.raises(FileNotFoundError):
        Pipeline(c, FakeAuditor(["PASS_CONSTRUCTION"]), runner=fake_runner).run()
