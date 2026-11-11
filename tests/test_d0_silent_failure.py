import json
from pathlib import Path
import pytest
from ssd_ci.runner import load_modules, run_scenario
from ssd_ci.scenario import parse_scenarios, SSDScenario

SCENARIO_PATH = Path("assets/scenarios/D0_SILENT_FAILURE.json")
ENGINE_DIR = Path("assets/engine_ref")


@pytest.fixture(scope="module")
def loaded_scenario() -> dict:
    with open(SCENARIO_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data[0]


@pytest.fixture(scope="module")
def engine_modules():
    return load_modules(ENGINE_DIR)


def test_d0_schema_validation(loaded_scenario):
    scenarios = parse_scenarios([loaded_scenario])
    assert len(scenarios) == 1
    sc = scenarios[0]
    assert sc.id == "D0-SILENT-FAILURE"
    assert sc.actors["operator"] == "controlled"
    assert sc.actors["telemetry_node"] == "npc"
    assert "telemetry_quarantined" in sc.variables
    assert sc.variables["telemetry_quarantined"].effect_role == "protected"


def test_d0_graph_enumeration_and_branches(engine_modules, loaded_scenario):
    result = run_scenario(engine_modules, loaded_scenario, max_paths=100, shuffle_seeds=(1, 2, 3))
    assert result["errors"] == []
    assert result["enumeration_complete"] is True
    assert result["enumerated"] == 2

    paths = result["paths"]
    safe_path = next(p for p in paths if p["positions"]["operator"] == "operator.terminal_safe")
    rejected_path = next(p for p in paths if p["positions"]["operator"] == "operator.terminal_rejected")

    # Weryfikacja sciezki bezpiecznej izolacji
    assert safe_path["world"]["telemetry_quarantined"] is True
    assert safe_path["world"]["system_mitigated"] is True
    assert safe_path["actions"]["isolate_icu_segment"] == "WYKONANE"

    # Weryfikacja sciezki zaniechania (bypass)
    assert rejected_path["world"]["telemetry_quarantined"] is False
    assert rejected_path["world"]["system_mitigated"] is True
    assert "isolate_icu_segment" not in rejected_path["actions"]