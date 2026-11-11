"""SSD CI/CD coordinator: deterministic engine -> Claude -> local validation -> guarded auto-fix.

No AI result can approve M2. All accepted reports carry validation_scope AI_CONSTRUCTION_ONLY.
"""
from __future__ import annotations
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable
from xml.etree import ElementTree as ET

from .clients import AuditorClient, GeneratorClient
from .models import AuditReport, ReportStatus, RunContext, ArtifactType, validate_audit_report
from .runner import canonical_json, engine_sources_sha, hash_engine, run_engine, sha_bytes
from .scenario import parse_scenarios

PRIORITY: dict[ReportStatus, int] = {
    ReportStatus.PASS_CONSTRUCTION: 0,
    ReportStatus.ESCALATE_HUMAN: 1,
    ReportStatus.FAIL: 2,
}


@dataclass(frozen=True)
class PipelineConfig:
    scenarios_path: Path
    engine_root: Path
    engine_baseline_path: Path
    prompt_path: Path
    report_schema_path: Path
    output_dir: Path
    invariant_version: str = "INV-1.0"
    run_id: str = "ssd-local"
    max_iterations: int = 3
    max_paths: int = 2000
    shuffles: tuple[int, ...] = (1, 2, 3)
    regressions: tuple[str, ...] = ("test_c0.py",)
    max_auditor_bytes: int = 2_500_000

    def __post_init__(self) -> None:
        if self.max_iterations < 1 or self.max_iterations > 3:
            raise ValueError("Safety policy: max_iterations must be 1..3")
        if self.max_paths < 1:
            raise ValueError("max_paths must be positive")
        if self.max_auditor_bytes < 1000:
            raise ValueError("max_auditor_bytes too small")


class PipelineError(RuntimeError):
    pass


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def _build_xml(ctx: RunContext, scenarios: list[dict[str, Any]], engine_report: dict[str, Any],
               engine_diff: dict[str, Any] | None, previous_report: dict[str, Any] | None) -> str:
    root = ET.Element("ssd_audit_request")
    for name, payload in (("run_context", ctx.model_dump(mode="json")),
                          ("scenario_json", scenarios), ("engine_report", engine_report),
                          ("engine_diff", engine_diff), ("previous_report", previous_report)):
        if payload is None:
            continue
        child = ET.SubElement(root, name, {"encoding": "application/json"})
        child.text = canonical_json(payload)
    return ET.tostring(root, encoding="unicode", short_empty_elements=False)


def _rank(status_a: ReportStatus, status_b: ReportStatus) -> ReportStatus:
    return status_a if PRIORITY[status_a] >= PRIORITY[status_b] else status_b


def _effective_status(model: AuditReport, engine: dict[str, Any], engine_changed: bool) -> tuple[ReportStatus, list[str]]:
    notes: list[str] = []
    status = model.status
    if engine_changed:
        status = _rank(status, ReportStatus.ESCALATE_HUMAN)
        notes.append("ENGINE_SEMANTICS_CHANGED: baseline digest differs")
    if not engine["enumeration_complete"]:
        status = _rank(status, ReportStatus.ESCALATE_HUMAN)
        notes.append("INCOMPLETE_INPUT: enumeration not complete")
    if engine["has_engine_errors"]:
        status = ReportStatus.FAIL
        notes.append("ENGINE_FAILURE: deterministic errors override auditor")
    if any(c.result == "FAIL" for c in model.checks) or any(f.severity in ("BLOCKER", "MAJOR") for f in model.findings):
        status = ReportStatus.FAIL
        notes.append("AUDIT_FINDINGS: at least one FAIL / MAJOR / BLOCKER")
    if (model.escalation.required or
        any(c.result in ("NOT_VERIFIABLE", "PENDING_IMPLEMENTATION") for c in model.checks)):
        status = _rank(status, ReportStatus.ESCALATE_HUMAN)
        notes.append("HUMAN_JUDGEMENT_NEEDED or pending verification")
    if status != model.status:
        notes.append(f"MODEL_STATUS_MISMATCH: model={model.status.value}, orchestrator={status.value}")
    return status, notes


def _validate_report(raw: str, ctx: RunContext, schema: dict[str, Any],
                     engine_report: dict[str, Any]) -> AuditReport:
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError("Report must be JSON object")
    report = validate_audit_report(obj, schema)
    if report.run_context.model_dump(mode="json") != ctx.model_dump(mode="json"):
        raise ValueError("run_context mismatch: refuses output from different audit")
    # For deterministic findings require code actually surfaced by runner, else invented evidence.
    deterministic_codes = {e.get("code") for e in engine_report["errors"]}
    for finding in report.findings:
        if finding.basis == "DETERMINISTIC_ENGINE" and finding.engine_error_code not in deterministic_codes:
            raise ValueError(f"Unverified deterministic finding {finding.finding_id}: {finding.engine_error_code}")
    return report


def _feedback_only(report: AuditReport) -> dict[str, Any]:
    """Strictly no other auditor content, scenarios or engine report is exposed."""
    generator_ids = {f.finding_id for f in report.findings if f.remediation.target == "GENERATOR"}
    return {
        "generator_feedback": {"items": [x.model_dump() for x in report.generator_feedback.items
                                          if x.finding_id in generator_ids]},
        "remediation": [
            {"finding_id": f.finding_id, "instruction": f.remediation.instruction,
             "must_not": list(f.remediation.must_not)}
            for f in report.findings if f.remediation.target == "GENERATOR"
        ],
    }


def _decode_pointer(path: str) -> list[str]:
    if not path.startswith("/"):
        raise PipelineError("JSON Pointer must be absolute")
    result: list[str] = []
    for segment in path[1:].split("/"):
        if re.search(r"~(?![01])", segment):
            raise PipelineError("Invalid JSON Pointer escape")
        result.append(segment.replace("~1", "/").replace("~0", "~"))
    return result


def apply_generator_patch(scenarios: list[dict[str, Any]], proposal: dict[str, Any]) -> list[dict[str, Any]]:
    """Apply only a narrow, scenario-turn-only JSON Patch to a copy; never original files.

    `remove`, changing hidden truth/definitions and any engine edits require a human.
    """
    if not isinstance(proposal, dict) or set(proposal) != {"patch"} or not isinstance(proposal["patch"], list):
        raise PipelineError("Invalid generator response")
    if not proposal["patch"] or len(proposal["patch"]) > 20:
        raise PipelineError("Empty or oversized patch; escalate to human")
    amended: Any = copy.deepcopy(scenarios)
    for item in proposal["patch"]:
        if not isinstance(item, dict) or set(item) != {"op", "path", "value"} or item["op"] not in ("add", "replace"):
            raise PipelineError("Only add/replace with explicit value is permitted")
        parts = _decode_pointer(item["path"])
        if len(parts) < 4 or not parts[0].isdigit() or parts[1] != "turns" or not parts[2].isdigit():
            raise PipelineError("Auto-fix restricted to /<scenario_index>/turns/<turn_index>/...")
        if int(parts[0]) >= len(amended):
            raise PipelineError("Bad scenario index")
        if any(p in {"effect_role", "effect_owner", "validation_status", "schema_version", "id", "graph"} for p in parts[3:]):
            raise PipelineError("Protected model/identity/graph metadata needs human review")
        target: Any = amended
        for part in parts[:-1]:
            if isinstance(target, list):
                if not part.isdigit() or int(part) >= len(target):
                    raise PipelineError("Invalid patch array index")
                target = target[int(part)]
            elif isinstance(target, dict):
                if part not in target:
                    raise PipelineError("Patch targets nonexistent parent")
                target = target[part]
            else:
                raise PipelineError("Non-container patch target")
        leaf = parts[-1]
        if isinstance(target, list):
            if leaf == "-" and item["op"] == "add":
                target.append(item["value"])
            elif leaf.isdigit():
                n = int(leaf)
                if item["op"] == "replace" and n < len(target):
                    target[n] = item["value"]
                elif item["op"] == "add" and n <= len(target):
                    target.insert(n, item["value"])
                else:
                    raise PipelineError("Invalid array patch")
            else:
                raise PipelineError("Non-numeric array index")
        elif isinstance(target, dict):
            if item["op"] == "replace" and leaf not in target:
                raise PipelineError("Cannot replace missing field")
            target[leaf] = item["value"]
        else:
            raise PipelineError("Invalid patch container")
    parse_scenarios(amended)
    return amended


class Pipeline:
    def __init__(self, config: PipelineConfig, auditor: AuditorClient,
                 generator: GeneratorClient | None = None,
                 runner: Callable[..., dict[str, Any]] = run_engine) -> None:
        self.config = config
        self.auditor = auditor
        self.generator = generator
        self.runner = runner

    def run(self) -> dict[str, Any]:
        c = self.config
        c.output_dir.mkdir(parents=True, exist_ok=True)
        source_bytes = c.scenarios_path.read_bytes()
        scenarios: list[dict[str, Any]] = json.loads(source_bytes)
        parse_scenarios(scenarios)
        schema: dict[str, Any] = json.loads(c.report_schema_path.read_text("utf-8"))
        from jsonschema import Draft202012Validator
        Draft202012Validator.check_schema(schema)
        if schema.get("title") != "SSD-AUDIT-REPORT 1.0":
            raise PipelineError("Wrong auditor report schema")
        prompt_bytes = c.prompt_path.read_bytes()
        prompt = prompt_bytes.decode("utf-8")
        if not prompt.strip():
            raise PipelineError("AUDYTOR_SYSTEM_PROMPT.md must not be empty")
        # README v1.1 requires the full schema in the prompt; this is a preflight
        # sanity check, not a proof that embedded copies match exactly.
        if '"report_version"' not in prompt or '"INV-16"' not in prompt:
            raise PipelineError("Prompt does not appear to contain the SSD 1.0 schema; provide original v1.1")
        prompt_hash = sha_bytes(prompt_bytes)
        engine_hash = hash_engine(c.engine_root)
        if not c.engine_baseline_path.is_file():
            raise PipelineError("Missing pinned engine SHA-256 baseline; do not assume unchanged")
        baseline = c.engine_baseline_path.read_text("utf-8").strip()
        if len(baseline) != 64 or any(a not in "0123456789abcdef" for a in baseline):
            raise PipelineError("Invalid pinned engine SHA-256 baseline")
        engine_changed = baseline != engine_hash
        if engine_changed and self.generator is not None:
            # Do not allow automatic repairs when engine changed; audit can still be run.
            no_autofix_reason = "Engine differs from baseline: human escalation required"
        else:
            no_autofix_reason = None
        history: list[dict[str, Any]] = []
        prev_report: dict[str, Any] | None = None
        result_status = ReportStatus.ESCALATE_HUMAN
        stop_reason = ""
        for iteration in range(1, c.max_iterations + 1):
            folder = c.output_dir / f"iteration_{iteration:02d}"
            folder.mkdir(parents=True, exist_ok=True)
            canonical = canonical_json(scenarios)
            (folder / "scenario.canonical.json").write_text(canonical, encoding="utf-8")
            sc_hash = sha_bytes(canonical.encode("utf-8"))
            engine_report = self.runner(scenarios, c.engine_root, max_paths=c.max_paths,
                                        shuffle_seeds=c.shuffles, regression_scripts=c.regressions)
            _write_json(folder / "engine_report.json", engine_report)
            ctx = RunContext(run_id=c.run_id, artifact_type=ArtifactType.BOTH if engine_changed else ArtifactType.SCENARIO,
                             scenario_ids=[s["id"] for s in scenarios], scenario_sha256=sc_hash,
                             engine_sha256=engine_hash, iteration=iteration, max_iterations=c.max_iterations,
                             auditor_prompt_sha256=prompt_hash, invariants_version=c.invariant_version)
            diff = {"engine_changed": True, "baseline_sha256": baseline,
                    "current_sha256": engine_hash} if engine_changed else None
            xml = _build_xml(ctx, scenarios, engine_report, diff, prev_report)
            if len(xml.encode("utf-8")) > c.max_auditor_bytes:
                result_status = ReportStatus.FAIL if engine_report["has_engine_errors"] else ReportStatus.ESCALATE_HUMAN
                stop_reason = "AUDITOR_PAYLOAD_EXCEEDS_LIMIT; no silent truncation"
                history.append({"iteration": iteration, "status": result_status.value, "reason": stop_reason})
                break
            (folder / "auditor_request.xml").write_text(xml, encoding="utf-8")
            audit: AuditReport | None = None
            errors: list[str] = []
            for attempt in (1, 2):
                try:
                    if attempt == 1:
                        message = xml
                    else:
                        retry_root = ET.fromstring(xml)
                        ET.SubElement(retry_root, "retry_instruction").text = (
                            "Return one strict JSON object matching schema and run_context; no markup."
                        )
                        message = ET.tostring(retry_root, encoding="unicode")
                        (folder / "auditor_request_retry.xml").write_text(message, encoding="utf-8")
                    raw = self.auditor.audit(system_prompt=prompt, message_xml=message)
                    (folder / f"auditor_response_attempt_{attempt}.txt").write_text(raw, encoding="utf-8")
                    audit = _validate_report(raw, ctx, schema, engine_report)
                    break
                except Exception as exc:
                    errors.append(f"attempt_{attempt}: {type(exc).__name__}: {str(exc)[:250]}")
            if audit is None:
                result_status = ReportStatus.FAIL if engine_report["has_engine_errors"] else ReportStatus.ESCALATE_HUMAN
                stop_reason = "AUDITOR_INVALID_AFTER_ONE_RETRY"
                _write_json(folder / "auditor_validation_errors.json", errors)
                history.append({"iteration": iteration, "status": result_status.value, "reason": stop_reason})
                break
            _write_json(folder / "auditor_validated.json", audit.model_dump(mode="json"))
            effective, notes = _effective_status(audit, engine_report, engine_changed)
            result_status = effective
            _write_json(folder / "decision.json", {"auditor_status": audit.status.value,
                        "effective_status": effective.value, "notes": notes})
            history.append({"iteration": iteration, "status": effective.value,
                            "auditor_status": audit.status.value, "notes": notes,
                            "scenario_sha256": sc_hash})
            prev_report = audit.model_dump(mode="json")
            if effective != ReportStatus.FAIL:
                stop_reason = "STOP_STATUS_" + effective.value
                break
            if iteration == c.max_iterations:
                stop_reason = "ITERATION_LIMIT_REQUIRES_HUMAN"
                break
            if no_autofix_reason:
                stop_reason = no_autofix_reason
                break
            if self.generator is None or not audit.generator_feedback.allowed:
                stop_reason = "NO_AUTHORIZED_GENERATOR_FEEDBACK"
                break
            feedback = _feedback_only(audit)
            if not feedback["generator_feedback"]["items"] and not feedback["remediation"]:
                stop_reason = "NO_GENERATOR_FIXES"
                break
            _write_json(folder / "generator_input_feedback_only.json", feedback)
            try:
                patch = self.generator.propose_patch(feedback)
                _write_json(folder / "generator_patch_proposal.json", patch)
                scenarios = apply_generator_patch(scenarios, patch)
            except Exception as exc:
                stop_reason = f"AUTO_FIX_REJECTED_REQUIRES_HUMAN: {type(exc).__name__}: {str(exc)[:250]}"
                break
        if not stop_reason:
            stop_reason = "ITERATION_LIMIT_REQUIRES_HUMAN"
        # FAIL is never weakened, but exhaustion additionally triggers human review.
        human_required = result_status != ReportStatus.PASS_CONSTRUCTION or stop_reason.startswith(("ITERATION", "AUTO_FIX"))
        result = {
            "pipeline_version": "SSD-CICD-ORCHESTRATOR 1.0", "run_id": c.run_id,
            "effective_status": result_status.value, "human_escalation": human_required,
            "human_validation_required": True, "validation_scope": "AI_CONSTRUCTION_ONLY",
            "reason": stop_reason, "iterations": history, "engine_changed": engine_changed,
            "artifact_hashes": {
                "source_scenario_sha256": sha_bytes(source_bytes),
                "latest_scenario_sha256": sha_bytes(canonical_json(scenarios).encode("utf-8")),
                "engine_sha256": engine_hash, "engine_baseline_sha256": baseline,
                "engine_files": engine_sources_sha(c.engine_root),
                "auditor_prompt_sha256": prompt_hash,
                "report_schema_sha256": sha_bytes(c.report_schema_path.read_bytes()),
            },
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(c.output_dir / "pipeline_result.json", result)
        return result
