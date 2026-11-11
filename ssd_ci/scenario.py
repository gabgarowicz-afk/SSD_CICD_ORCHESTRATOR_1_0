"""Typed, mostly strict representation of SSD M2 v0.3 B2.2 / C0 fixtures.

No invented M2 JSON Schema: predicates and operations use documented B2.2 keys,
with semantic validation delegated to actual deterministic engine modules.
"""
from __future__ import annotations
from typing import Any, Literal, Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator

JSON = Any  # B2.2 includes heterogeneous, recursively structured predicates/ops.


class ScenarioModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Predicate(ScenarioModel):
    var: str | None = None
    op: str | None = None
    value: JSON = None
    choice: str | None = None
    is_: JSON = Field(default=None, alias="is")
    all: list["Predicate"] | None = None
    any: list["Predicate"] | None = None
    not_: "Predicate | None" = Field(default=None, alias="not")
    observed: str | None = None
    reported: JSON = None


class EffectOwner(ScenarioModel):
    actions: list[str] = Field(min_length=1)
    stage: Literal["execution", "confirmation"]


class Variable(ScenarioModel):
    type: Literal["bool", "int", "enum", "str"]
    effect_role: Literal["ordinary", "protected"]
    effect_owner: EffectOwner | None = None
    enum: list[JSON] | None = None
    min: int | None = None
    max: int | None = None

    @model_validator(mode="after")
    def guarded(self) -> "Variable":
        if self.effect_role == "protected" and self.effect_owner is None:
            raise ValueError("Protected effect requires effect_owner")
        if self.effect_role == "ordinary" and self.effect_owner is not None:
            raise ValueError("Ordinary variable cannot have effect_owner")
        if self.type == "enum" and not self.enum:
            raise ValueError("Enum variable needs nonempty values")
        return self


class Operation(ScenarioModel):
    op: Literal["set", "inc", "status", "observe"]
    var: str | None = None
    value: JSON = None
    action: str | None = None
    actor: str | None = None
    message: "Observation | None" = None
    evidence_source: str | None = None
    status_path: list[str] | None = None
    via: list[str] | None = None


class Observation(ScenarioModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    text: str = Field(min_length=1)
    claim: Predicate
    mode: Literal["factual", "mistake", "deliberate_false", "unverified", "report"]
    reference: str | None = None


class ActionEffect(ScenarioModel):
    kind: Literal["action"]
    action_id: str
    ops: list[Operation]
    consequence: str


class InactionEffect(ScenarioModel):
    kind: Literal["inaction"]
    category: Literal["wait", "defer", "omit"]
    ops: list[Operation]
    consequence: str


class Variant(ScenarioModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    effect: Annotated[ActionEffect | InactionEffect, Field(discriminator="kind")]
    grounds: list[str]
    benefits: str
    limits: str
    risks: str
    availability: Predicate | None = None
    discloses_observation: str | None = None

    @model_validator(mode="after")
    def gate_uses_knowledge_only(self) -> "Variant":
        if self.availability is None:
            return self
        if self.discloses_observation is None:
            raise ValueError("Availability requires an explicit disclosed observation")
        if self.availability.model_dump(exclude_none=True, by_alias=True) != {"observed": self.discloses_observation}:
            raise ValueError("Availability must refer to received observation only")
        return self


class Evidence(ScenarioModel):
    source: str
    kind: str
    basis: str


class Rule(ScenarioModel):
    id: str
    actor: str | None = None
    when: Predicate | None = None
    ops: list[Operation]
    grounds: list[str]
    effect_of: str | None = None
    evidence: Evidence | None = None
    preconditions: list[Predicate] | None = None


class Turn(ScenarioModel):
    choices: dict[str, list[Variant]]
    opening: list[Rule] = Field(default_factory=list)
    resolve: list[Rule] = Field(default_factory=list)
    npc: list[Rule] = Field(default_factory=list)
    consequence: list[Rule] = Field(default_factory=list)


class Configuration(ScenarioModel):
    id: str
    world: dict[str, JSON]
    knowledge: dict[str, list[Observation]]
    history: list[str] = Field(default_factory=list)


class Edge(ScenarioModel):
    to: str
    when: Predicate | None = None


class GraphNode(ScenarioModel):
    actor: str
    template_turn: int | None = None
    terminal: bool = False
    edges: list[Edge] = Field(default_factory=list)


class Graph(ScenarioModel):
    start: dict[str, str]
    nodes: dict[str, GraphNode]
    max_turns: int = Field(ge=1)
    limit_end: str | None = None


class SSDScenario(ScenarioModel):
    id: str = Field(min_length=1)
    source_id: str | None = None
    title: str
    schema_version: str
    validation_status: Literal["AI_CONSTRUCTION_ONLY", "PRÓBA_KONSTRUKCYJNA_C0"] = "AI_CONSTRUCTION_ONLY"
    actors: dict[str, Literal["controlled", "npc"]]
    assumptions: dict[str, str] = Field(default_factory=dict)
    variables: dict[str, Variable]
    configurations: list[Configuration] = Field(min_length=1)
    turns: list[Turn] = Field(min_length=1)
    conflict_rules: list[dict[str, JSON]] = Field(default_factory=list)
    source_branch_ids: dict[str, JSON] | None = None
    documented_changes: list[str] | None = None
    graph: Graph | None = None

    @model_validator(mode="after")
    def validate_references(self) -> "SSDScenario":
        if not any(k == "controlled" for k in self.actors.values()):
            raise ValueError("At least one controlled actor required")
        for c in self.configurations:
            if set(c.world) != set(self.variables):
                raise ValueError(f"{c.id}: world variables differ from declared variables")
            if set(c.knowledge) - set(self.actors):
                raise ValueError(f"{c.id}: unknown knowledge recipients")
        for turn in self.turns:
            for role in turn.choices:
                if self.actors.get(role) != "controlled":
                    raise ValueError(f"Not controlled: {role}")
        return self


def parse_scenarios(source: object) -> list[SSDScenario]:
    if not isinstance(source, list) or not source:
        raise ValueError("Scenario input must be a nonempty list")
    parsed = [SSDScenario.model_validate(item) for item in source]
    if len({s.id for s in parsed}) != len(parsed):
        raise ValueError("Scenario IDs must be unique")
    return parsed


Predicate.model_rebuild()
Operation.model_rebuild()
