"""Pydantic v2 view of SSD-AUDIT-REPORT 1.0 (authoritative validator: JSON Schema).

Literal identifiers, nullability and length limits mirror the delivered schema.
Cross-field JSON-Schema conditionals remain enforced by Draft202012Validator.
"""
from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReportStatus(str, Enum):
    PASS_CONSTRUCTION = "PASS_CONSTRUCTION"
    FAIL = "FAIL"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"


class ArtifactType(str, Enum):
    SCENARIO = "SCENARIO"
    ENGINE_CHANGE = "ENGINE_CHANGE"
    BOTH = "BOTH"


InvariantId = Literal[
    "INV-01", "INV-02", "INV-03", "INV-04", "INV-05", "INV-06",
    "INV-07", "INV-08", "INV-09", "INV-10", "INV-11", "INV-12",
    "INV-13", "INV-14", "INV-15", "INV-16",
]
INVARIANT_IDS: frozenset[str] = frozenset(f"INV-{i:02d}" for i in range(1, 17))
SHA256 = str


class RunContext(StrictModel):
    run_id: str = Field(min_length=1, max_length=128)
    artifact_type: ArtifactType
    scenario_ids: list[str]
    scenario_sha256: SHA256 | None = Field(pattern=r"^[0-9a-f]{64}$")
    engine_sha256: SHA256 = Field(pattern=r"^[0-9a-f]{64}$")
    iteration: int = Field(ge=1)
    max_iterations: int = Field(ge=1, le=10)
    auditor_prompt_sha256: SHA256 = Field(pattern=r"^[0-9a-f]{64}$")
    invariants_version: str = Field(pattern=r"^INV-[0-9]+\.[0-9]+$")

    @model_validator(mode="after")
    def unique_scenarios(self) -> "RunContext":
        if any(not name for name in self.scenario_ids) or len(self.scenario_ids) != len(set(self.scenario_ids)):
            raise ValueError("scenario_ids must be unique nonempty strings")
        return self


class Check(StrictModel):
    invariant: InvariantId
    result: Literal["PASS", "FAIL", "NOT_APPLICABLE", "NOT_VERIFIABLE", "PENDING_IMPLEMENTATION"]
    basis: Literal["DETERMINISTIC_ENGINE", "STATIC_READING", "SEMANTIC_JUDGEMENT", "NONE"]
    note: str = Field(max_length=600)


ENGINE_ERROR_CODES: frozenset[str] = frozenset({
    "ACTION_ALREADY_INITIALIZED", "AMBIGUOUS_STATUS_PATH", "BAD_CLAIM",
    "BRAMKA_BEZ_UZASADNIENIA_INFORMACYJNEGO", "CHOICES_AFTER_END", "CHOICE_NOT_VISIBLE",
    "DEPENDENCY_SAME_PHASE", "DUPLICATE_OBSERVATION", "EFFECT_ACTION_NOT_SELECTED",
    "EMPTY_GRAPH", "ENGINE_CANNOT_SELF_CONFIRM_RESULT", "ENGINE_PRECONDITIONS_NOT_MET",
    "ENGINE_PRECONDITIONS_REQUIRED", "FORBIDDEN_GATE_REFERENCE", "GRAPH_ALREADY_FINISHED",
    "GRAPH_ALREADY_TERMINAL", "GRAPH_CHOICE_NOT_VISIBLE", "GRAPH_EDGE_AMBIGUOUS_OR_MISSING",
    "ILLEGAL_STATUS_TRANSITION", "INCOMPLETE_CHOICES", "INVALID_CHOICE",
    "INVALID_CONFLICT_POLICY", "INVALID_DEFINITION", "INVALID_EFFECT_EXECUTOR",
    "INVALID_EFFECT_OWNER", "INVALID_ENGINE_PRECONDITION", "INVALID_ENGINE_PROOF",
    "INVALID_ENUM", "INVALID_GATE", "INVALID_GRAPH", "INVALID_GRAPH_START_ACTORS",
    "INVALID_INC", "INVALID_INC_TYPE", "INVALID_NPC_PROOF", "INVALID_OBSERVATION",
    "INVALID_PREDICATE", "INVALID_STATUS_PATH", "INVALID_TURN_LIMIT", "INVALID_TYPE",
    "MISCLASSIFIED_FALSE_INFORMATION", "MISSING_GRAPH", "MISSING_RULE_GROUNDS",
    "NIESPOJNA_BRAMKA_INFORMACYJNA", "NO_STATUS_CHANGE", "NO_TERMINAL_NODE",
    "NO_VISIBLE_CHOICE", "PROTECTED_EFFECT_AT_SELECTION", "PROTECTED_EFFECT_IN_SELECTION_PHASE",
    "PROTECTED_EFFECT_WITHOUT_EVIDENCE", "PROTECTED_EFFECT_WITHOUT_EXECUTION",
    "PROTECTED_EFFECT_WITHOUT_STATUS", "REPEATED_ACTION_STILL_ACTIVE",
    "RESERVED_EXECUTOR_NAME", "RESOURCE_CONSTRAINT", "RESULT_REQUIRES_EVIDENCE",
    "RESULT_REQUIRES_GROUND", "RESULT_REQUIRES_PRIOR_ACTION",
    "RESULT_SAME_PHASE_AS_EXECUTION", "RESULT_SOURCE_NOT_INDEPENDENT",
    "RESULT_TRANSITION_NOT_SKIPPABLE", "SAME_PHASE_DEPENDENCY", "STATUS_UNINITIALIZED",
    "UNAUTHORIZED_EFFECT_OWNER", "UNCLASSIFIED_EFFECT", "UNDECLARED_FALSE_INFORMATION",
    "UNKNOWN_ACTOR", "UNKNOWN_EFFECT_OWNER", "UNKNOWN_OP", "UNKNOWN_PICK_ACTORS",
    "UNKNOWN_POSITION_ACTOR", "UNKNOWN_REFERENCE_TIME", "UNSYNCHRONIZED_TEMPLATES",
    "WRITE_CONFLICT",
})


class FindingLocation(StrictModel):
    scenario_id: str | None = Field(default=None, min_length=1)
    json_path: str | None = Field(default=None, min_length=1, max_length=300)
    rule_ids: list[str]
    turn: int | None = Field(default=None, ge=0)
    phase: Literal["selection", "opening", "resolve", "npc", "consequence", "graph", "definition"] | None
    actor: str | None = Field(default=None, min_length=1)
    configurations: list[str]
    engine_file: str | None = Field(default=None, min_length=1)


class Remediation(StrictModel):
    target: Literal["GENERATOR", "ENGINE_TEAM", "SCENARIO_AUTHOR", "HUMAN_REVIEW"]
    instruction: str = Field(max_length=1500)
    must_not: list[str] = Field(max_length=10)


class Finding(StrictModel):
    finding_id: str = Field(pattern=r"^F-[0-9]{3}$")
    invariant: InvariantId
    severity: Literal["BLOCKER", "MAJOR", "MINOR", "NOTE"]
    basis: Literal["DETERMINISTIC_ENGINE", "STATIC_READING", "SEMANTIC_JUDGEMENT"]
    engine_error_code: str | None
    location: FindingLocation
    description: str = Field(min_length=1, max_length=1200)
    evidence_excerpt: str = Field(max_length=500)
    remediation: Remediation

    @model_validator(mode="after")
    def known_error_codes(self) -> "Finding":
        if self.engine_error_code is not None and self.engine_error_code not in ENGINE_ERROR_CODES:
            raise ValueError(f"Unrecognized engine error code {self.engine_error_code}")
        if self.basis == "DETERMINISTIC_ENGINE" and self.engine_error_code is None:
            raise ValueError("Deterministic finding requires engine_error_code")
        if self.basis == "SEMANTIC_JUDGEMENT" and self.severity == "BLOCKER":
            raise ValueError("Semantic finding cannot be BLOCKER")
        return self


class HumanQuestion(StrictModel):
    to_role: Literal["METODYK", "PROGRAMISTA_OPERATOR", "EKSPERT_KRYZYSOWY", "WLASCICIEL_PROJEKTU"]
    question: str = Field(min_length=1, max_length=800)
    related_findings: list[str]


class Escalation(StrictModel):
    required: bool
    reasons: list[Literal["INCOMPLETE_INPUT", "ENGINE_SEMANTICS_CHANGED", "ITERATION_LIMIT",
                          "HUMAN_JUDGEMENT_NEEDED", "SUSPECTED_ENGINE_DEFECT",
                          "PROMPT_INJECTION_SUSPECTED", "AUDITOR_CAPACITY"]]
    questions_for_human: list[HumanQuestion] = Field(max_length=20)

    @model_validator(mode="after")
    def unique_reasons(self) -> "Escalation":
        if len(self.reasons) != len(set(self.reasons)):
            raise ValueError("Duplicate escalation reasons")
        return self


class GeneratorFeedbackItem(StrictModel):
    finding_id: str = Field(pattern=r"^F-[0-9]{3}$")
    instruction: str = Field(min_length=1, max_length=1500)


class GeneratorFeedback(StrictModel):
    allowed: bool
    items: list[GeneratorFeedbackItem]


class AuditReport(StrictModel):
    report_version: Literal["SSD-AUDIT-REPORT 1.0"]
    run_context: RunContext
    status: ReportStatus
    validation_scope: Literal["AI_CONSTRUCTION_ONLY"]
    human_validation_required: Literal[True]
    summary: str = Field(min_length=1, max_length=800)
    checks: list[Check] = Field(min_length=16, max_length=16)
    findings: list[Finding] = Field(max_length=200)
    escalation: Escalation
    generator_feedback: GeneratorFeedback
    limitations: list[str]

    @model_validator(mode="after")
    def checks_unique_and_consistent(self) -> "AuditReport":
        if {x.invariant for x in self.checks} != INVARIANT_IDS:
            raise ValueError("Exactly INV-01 through INV-16 required")
        if len({f.finding_id for f in self.findings}) != len(self.findings):
            raise ValueError("finding_id must be unique")
        ids = {f.finding_id for f in self.findings}
        if any(item.finding_id not in ids for item in self.generator_feedback.items):
            raise ValueError("generator_feedback contains unknown finding_id")
        if self.status == ReportStatus.ESCALATE_HUMAN and (not self.escalation.required or not self.escalation.reasons):
            raise ValueError("Escalation status requires reasons")
        return self


def validate_audit_report(data: dict[str, object], schema: dict[str, object]) -> AuditReport:
    """Both author-provided authoritative schema and local typed model must accept."""
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(data)
    return AuditReport.model_validate(data)
