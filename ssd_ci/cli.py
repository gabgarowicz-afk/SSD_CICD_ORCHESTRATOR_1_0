"""CLI entrypoint for local deterministic checks and live Claude/OpenAI CI runs."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from .clients import ClaudeHTTPAuditor, OpenAIPatchGenerator
from .orchestrator import Pipeline, PipelineConfig
from .runner import hash_engine, run_engine

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / "assets/schema/raport_audytu.schema.json").is_file():
    ROOT = Path(__file__).resolve().parent  # installed wheel package data


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ssd-audit", description="SSD construction audit — not independent validation")
    commands = p.add_subparsers(dest="command", required=True)
    for mode in ("check", "run"):
        cmd = commands.add_parser(mode)
        cmd.add_argument("--scenarios", type=Path, default=ROOT / "assets/scenarios/C0_SCENARIUSZE_GRAFOWE.json")
        cmd.add_argument("--engine-root", type=Path, default=ROOT / "assets/engine_ref")
        cmd.add_argument("--max-paths", type=int, default=2000)
        cmd.add_argument("--shuffles", type=int, default=3)
        cmd.add_argument("--regression", action="append", default=None, help="Trusted test_*.py in engine root")
        cmd.add_argument("--output", type=Path, default=Path("artifacts/ssd_audit"))
    live = commands.choices["run"]
    live.add_argument("--prompt", required=True, type=Path, help="Original AUDYTOR_SYSTEM_PROMPT.md v1.1")
    live.add_argument("--schema", type=Path, default=ROOT / "assets/schema/raport_audytu.schema.json")
    live.add_argument("--engine-baseline", type=Path, default=ROOT / "assets/engine_ref/BASELINE_ENGINE_SHA256.txt")
    live.add_argument("--claude-model", required=True, help="Pinned Claude model ID")
    live.add_argument("--openai-model", help="Pinned OpenAI model ID, if enabled")
    live.add_argument("--disable-autofix", action="store_true")
    live.add_argument("--max-iterations", type=int, default=3)
    live.add_argument("--run-id", default="ssd-local")
    live.add_argument("--invariants-version", default="INV-1.0")
    live.add_argument("--max-auditor-bytes", type=int, default=2_500_000)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        seeds = tuple(range(1, args.shuffles + 1))
        regressions = tuple(args.regression) if args.regression is not None else ("test_c0.py",)
        if args.command == "check":
            source = json.loads(args.scenarios.read_text("utf-8"))
            report = run_engine(source, args.engine_root, max_paths=args.max_paths,
                                shuffle_seeds=seeds, regression_scripts=regressions)
            args.output.mkdir(parents=True, exist_ok=True)
            (args.output / "engine_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            summary = {"enumerated": report["total_paths"], "complete": report["enumeration_complete"],
                       "shuffles_checked": report["total_shuffles"],
                       "regressions_ok": report["regressions"]["ok"],
                       "errors": len(report["errors"]), "engine_sha256": hash_engine(args.engine_root),
                       "validation_scope": "AI_CONSTRUCTION_ONLY"}
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return 0 if not report["errors"] and report["enumeration_complete"] else 2
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is required for live run")
        if not args.disable_autofix and not args.openai_model:
            raise ValueError("Provide --openai-model or use --disable-autofix")
        if not args.disable_autofix and not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is required for auto-fix")
        cfg = PipelineConfig(scenarios_path=args.scenarios, engine_root=args.engine_root,
                             engine_baseline_path=args.engine_baseline, prompt_path=args.prompt,
                             report_schema_path=args.schema, output_dir=args.output,
                             invariant_version=args.invariants_version, run_id=args.run_id,
                             max_iterations=args.max_iterations, max_paths=args.max_paths,
                             shuffles=seeds, regressions=regressions,
                             max_auditor_bytes=args.max_auditor_bytes)
        claude = ClaudeHTTPAuditor(model=args.claude_model)
        generator = None if args.disable_autofix else OpenAIPatchGenerator(model=args.openai_model)
        result = Pipeline(cfg, claude, generator).run()
        print(json.dumps({k: result[k] for k in ("effective_status", "reason", "human_escalation", "run_id")},
                         ensure_ascii=False, indent=2))
        return 0 if result["effective_status"] == "PASS_CONSTRUCTION" else 2
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        # Fail closed. Never print API keys or entire untrusted API bodies.
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)[:500],
                          "status": "ESCALATE_HUMAN"}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
