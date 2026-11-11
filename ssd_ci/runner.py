"""Deterministic engine-first validation and exhaustive choice enumeration.

Runs actual C0/B2.2 engine APIs, never a semantic LLM approximation. Fail closed:
limit overflow, invalid scenario, unavailable modules and regression failures are explicit.
"""
from __future__ import annotations
import copy
import hashlib
import importlib
import itertools
import json
from pathlib import Path
import random
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

from .scenario import parse_scenarios

ENGINE_FILES = ("m2_fazowy_etapA.py", "m2_przedB_poprawka_statusow.py", "m2_etapB.py", "m2_etapC_graf.py")


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_engine(engine_root: Path) -> str:
    """Hash filenames and bytes, avoiding concatenation ambiguity and path variability."""
    h = hashlib.sha256()
    for name in ENGINE_FILES:
        path = engine_root / name
        data = path.read_bytes()
        h.update(len(name.encode()).to_bytes(8, "big"))
        h.update(name.encode())
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def engine_sources_sha(engine_root: Path) -> dict[str, str]:
    return {name: sha_bytes((engine_root / name).read_bytes()) for name in ENGINE_FILES}


@dataclass(frozen=True)
class EngineModules:
    b: Any
    c: Any


def load_modules(engine_root: Path) -> EngineModules:
    """Import a fixed, trusted local engine tree, not arbitrary scenario-provided code."""
    if any(not (engine_root / x).is_file() for x in ENGINE_FILES):
        raise FileNotFoundError("Incomplete trusted engine root")
    path = str(engine_root.resolve())
    if path not in sys.path:
        sys.path.insert(0, path)
    # The runner is intentionally single-engine-per-process (no concurrent mixed versions).
    b = importlib.import_module("m2_etapB")
    c = importlib.import_module("m2_etapC_graf")
    actual = Path(b.__file__).resolve().parent
    if actual != engine_root.resolve() or Path(c.__file__).resolve().parent != actual:
        raise RuntimeError("Engine import cache belongs to different root; start a new process")
    return EngineModules(b=b, c=c)


def _error(exc: Exception, where: dict[str, Any]) -> dict[str, Any]:
    return {
        **where,
        "code": str(getattr(exc, "code", type(exc).__name__)),
        "detail": str(getattr(exc, "detail", str(exc)))[:1000],
    }


def _b_menu(b: Any, sc: dict[str, Any], state: dict[str, Any], turn_idx: int) -> dict[str, list[str]]:
    t = sc["turns"][turn_idx]
    candidate = copy.deepcopy(state)
    b.run_phase(candidate, sc, turn_idx + 1, "opening", t.get("opening", []), {})
    return {a: [o["id"] for o in b.visible_options(sc, candidate, turn_idx + 1, a)] for a in sorted(t["choices"])} 


def _b_step(b: Any, sc: dict[str, Any], st: dict[str, Any], ix: int, picks: dict[str, str]) -> dict[str, Any]:
    """Small step adapter for existing B.execute; same phase ordering and operations."""
    w = copy.deepcopy(st)
    t = sc["turns"][ix]
    b.run_phase(w, sc, ix + 1, "opening", t.get("opening", []), {})
    if set(picks) != set(t["choices"]):
        b.error("INCOMPLETE_CHOICES", repr(picks))
    synthetic = []
    selected: set[str] = set()
    for a, selected_variant in sorted(picks.items()):
        options = {o["id"]: o for o in b.visible_options(sc, w, ix + 1, a)}
        if selected_variant not in options:
            b.error("CHOICE_NOT_VISIBLE", f"{a}={selected_variant}")
        option = options[selected_variant]
        ef = option["effect"]
        if ef["kind"] == "action":
            aid = ef["action_id"]
            if aid in w["actions"] or aid in selected:
                b.error("ACTION_ALREADY_INITIALIZED", aid)
            selected.add(aid)
            w["actions"][aid] = "WYBRANE"
            w["action_meta"][aid] = {"selected_by": a, "selected_turn": ix + 1}
            w["trace"].append({"turn": ix + 1, "phase": "choice", "actor": a,
                               "choice": selected_variant, "action": aid, "status": "WYBRANE"})
        else:
            w["trace"].append({"turn": ix + 1, "phase": "choice", "actor": a,
                               "choice": selected_variant, "inaction": ef["category"],
                               "consequence": ef["consequence"]})
        synthetic.append({"id": f"CHOICE-{ix+1}-{a}-{selected_variant}", "when": None,
                          "ops": copy.deepcopy(ef["ops"]), "grounds": option["grounds"]})
    w["choices"].append(copy.deepcopy(picks))
    b.run_phase(w, sc, ix + 1, "resolve", t.get("resolve", []) + synthetic, picks)
    for phase in ("npc", "consequence"):
        b.run_phase(w, sc, ix + 1, phase, t.get(phase, []), picks)
    return w


def _c_menu(mod: EngineModules, sc: dict[str, Any], state: dict[str, Any]) -> dict[str, list[str]]:
    w = copy.deepcopy(state)
    active = {actor: node for actor, node in w["positions"].items()
              if not sc["graph"]["nodes"][node].get("terminal")}
    if not active:
        return {}
    templates = {sc["graph"]["nodes"][node]["template_turn"] for node in active.values()}
    if len(templates) != 1:
        mod.c.err("UNSYNCHRONIZED_TEMPLATES", repr(templates))
    turn_idx = next(iter(templates)) - 1
    mod.b.run_phase(w, sc, w["graph_turn"] + 1, "opening", sc["turns"][turn_idx].get("opening", []), {})
    return {a: [o["id"] for o in mod.c.available(sc, w, a)] for a in sorted(active)}


def _digest_state(st: dict[str, Any]) -> str:
    payload = {k: st.get(k) for k in ("world", "actions", "knowledge", "positions", "graph_end", "action_occurrences")}
    return sha_bytes(canonical_json(payload).encode("utf-8"))


def _shuffle(sc: dict[str, Any], seed: int) -> dict[str, Any]:
    item = copy.deepcopy(sc)
    rng = random.Random(seed)
    for t in item["turns"]:
        for phase in ("opening", "resolve", "npc", "consequence"):
            rng.shuffle(t.get(phase, []))
    return item


def _terminal_view(st: dict[str, Any], cfg: str, choices: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "configuration": cfg, "choices": choices,
        "outcome_sha256": _digest_state(st),
        "world": st["world"], "actions": st["actions"],
        "positions": st.get("positions", {}),
        "graph_end": st.get("graph_end"),
        "knowledge": {a: [{"id": v["id"], "text": v["text"], "source": v["source"]}
                          for v in obs] for a, obs in st["knowledge"].items()},
    }


def _iter_choices(available: dict[str, list[str]]) -> list[dict[str, str]]:
    if not available:
        return []
    keys = sorted(available)
    if any(not available[k] for k in keys):
        return []
    return [dict(zip(keys, combination)) for combination in itertools.product(*(available[k] for k in keys))]


def run_scenario(mod: EngineModules, scenario: dict[str, Any], *, max_paths: int,
                 shuffle_seeds: tuple[int, ...]) -> dict[str, Any]:
    ident = scenario["id"]
    graph = isinstance(scenario.get("graph"), dict)
    errors: list[dict[str, Any]] = []
    paths: list[dict[str, Any]] = []
    shuffles_checked = 0
    exhaustive = True
    try:
        static = mod.c.validate_graph(scenario) if graph else mod.b.validate_definition(scenario)
        information_audit = mod.b.static_information_audit(scenario)
        static = list(dict.fromkeys([*static, *information_audit.get("definition_errors", [])]))
    except Exception as exc:
        static = [str(exc)]
        information_audit = {"error": str(exc)}
    if static:
        errors.extend({"configuration": None, "stage": "definition", "code": "INVALID_DEFINITION", "detail": value}
                      for value in static)
        return {"scenario_id": ident, "static": static, "information_audit": information_audit,
                "paths": [], "errors": errors, "enumeration_complete": False,
                "enumerated": 0, "shuffles_checked": 0}
    for cfg in scenario["configurations"]:
        try:
            initial = mod.c.new_state(scenario, cfg) if graph else mod.b.initial(scenario, cfg)
        except Exception as exc:
            errors.append(_error(exc, {"configuration": cfg["id"], "stage": "initial"}))
            exhaustive = False
            continue
        stack: list[tuple[dict[str, Any], list[dict[str, str]]]] = [(initial, [])]
        while stack:
            if len(paths) + len(stack) > max_paths:
                exhaustive = False
                errors.append({"configuration": cfg["id"], "stage": "enumeration",
                               "code": "ENUMERATION_LIMIT_EXCEEDED", "detail": f"max_paths={max_paths}"})
                stack.clear()
                break
            state, sequence = stack.pop()
            at_end = state.get("graph_end") is not None if graph else len(sequence) == len(scenario["turns"])
            if at_end:
                paths.append(_terminal_view(state, cfg["id"], sequence))
                if shuffle_seeds:
                    for seed in shuffle_seeds:
                        shuffled = _shuffle(scenario, seed)
                        try:
                            check = (mod.c.execute_graph(shuffled, cfg, sequence) if graph
                                     else mod.b.execute(shuffled, cfg, sequence))
                            shuffles_checked += 1
                            if _digest_state(check) != _digest_state(state):
                                errors.append({"configuration": cfg["id"], "stage": "shuffle",
                                               "code": "SHUFFLE_DIFFERENCE", "seed": seed,
                                               "choices": sequence})
                        except Exception as exc:
                            errors.append(_error(exc, {"configuration": cfg["id"],
                                                       "stage": "shuffle", "seed": seed}))
                continue
            try:
                available = (_c_menu(mod, scenario, state) if graph else
                             _b_menu(mod.b, scenario, state, len(sequence)))
                candidates = _iter_choices(available)
                if not candidates:
                    errors.append({"configuration": cfg["id"], "stage": "options",
                                   "code": "NO_VISIBLE_CHOICE", "choices": sequence})
                    exhaustive = False
                    continue
                for picks in reversed(candidates):
                    working = copy.deepcopy(state)
                    try:
                        if graph:
                            mod.c.run_turn(working, scenario, picks)
                        else:
                            working = _b_step(mod.b, scenario, working, len(sequence), picks)
                        stack.append((working, [*sequence, picks]))
                    except Exception as exc:
                        errors.append(_error(exc, {"configuration": cfg["id"],
                                                   "stage": "execute", "choices": [*sequence, picks]}))
            except Exception as exc:
                exhaustive = False
                errors.append(_error(exc, {"configuration": cfg["id"], "stage": "options", "choices": sequence}))
    return {
        "scenario_id": ident, "static": static, "information_audit": information_audit,
        "paths": paths, "errors": errors,
        "enumeration_complete": exhaustive and not errors,
        "enumerated": len(paths), "shuffles_checked": shuffles_checked,
    }


def run_regressions(engine_root: Path, scripts: tuple[str, ...], timeout_s: int = 120) -> dict[str, Any]:
    outputs: list[dict[str, Any]] = []
    for name in scripts:
        # No arbitrary shell, no paths outside trusted repo.
        if not re.fullmatch(r"test_[A-Za-z0-9_]+\.py", name) or not (engine_root / name).is_file():
            outputs.append({"script": name, "ok": False, "error": "INVALID_REGRESSION_SCRIPT"})
            continue
        try:
            p = subprocess.run([sys.executable, "-B", str((engine_root / name).resolve())], cwd=engine_root,
                               text=True, capture_output=True, timeout=timeout_s, check=False)
            outputs.append({"script": name, "ok": p.returncode == 0, "returncode": p.returncode,
                            "stdout": p.stdout[-12000:], "stderr": p.stderr[-12000:]})
        except subprocess.TimeoutExpired:
            outputs.append({"script": name, "ok": False, "error": "REGRESSION_TIMEOUT"})
    return {"runs": outputs, "ok": all(x["ok"] for x in outputs)}


def run_engine(source: list[dict[str, Any]], engine_root: Path, *, max_paths: int = 2000,
               shuffle_seeds: tuple[int, ...] = (1, 2, 3),
               regression_scripts: tuple[str, ...] = ("test_c0.py",)) -> dict[str, Any]:
    typed = parse_scenarios(source)
    if max_paths < 1:
        raise ValueError("max_paths must be positive")
    mod = load_modules(engine_root)
    records = [run_scenario(mod, raw, max_paths=max_paths, shuffle_seeds=shuffle_seeds)
               for raw in source]
    regress = run_regressions(engine_root, regression_scripts)
    errors = [*({"scenario_id": r["scenario_id"], **e} for r in records for e in r["errors"]),
              *({"stage": "regression", **e} for e in regress["runs"] if not e["ok"])]
    # All path outputs retained in local report, not silently truncated; agent payload size
    # is controlled in CLI and must fail closed rather than omit enumeration evidence.
    return {
        "runner_version": "SSD-ENGINE-RUNNER 1.0", "scenario_ids": [x.id for x in typed],
        "results": records, "regressions": regress,
        "total_paths": sum(r["enumerated"] for r in records),
        "total_shuffles": sum(r["shuffles_checked"] for r in records),
        "enumeration_complete": all(r["enumeration_complete"] for r in records),
        "errors": errors,
        # A bounded enumerator is incomplete input, not a semantic engine defect.
        "has_engine_errors": any(e.get("code") != "ENUMERATION_LIMIT_EXCEEDED" for e in errors),
    }
