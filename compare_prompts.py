"""Measure what the specialized prompt (house rules + few-shot examples) changes.

Each request in REQUESTS goes through the AI Planner with the baseline prompt and with the
specialized prompt. Every proposed task is scored against the house rules (house_rules.py),
a summary is printed, and the full comparison is written to logs/specialization_comparison.md.

The requests give no durations, so the house durations apply to every task.

Usage:
    python compare_prompts.py            # 3 runs per prompt (36 Haiku calls, well under 5 cents)
    python compare_prompts.py --runs 1
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

from ai_planner import PlanResult, plan_request
from house_rules import RULE_NAMES, check_house_rules, check_task, summarize
from llm_client import ClaudeClient, LLMError
from pawpal_logging import setup_logging
from sample_data import sample_owner

REQUESTS = [
    "Feed Mochi in the morning and evening, and give him his heart pill with breakfast",
    "Luna needs her eye drops at 9am and 9pm",
    "Take Mochi for a walk at 7am and play fetch with him after work",
    "Clean Luna's litter box every night and feed her at 8am and 6pm",
    "Mochi has a vet checkup at 2pm and needs his allergy medicine every evening",
    "Brush Luna and trim Mochi's nails on Saturday morning",
]
OUTPUT = Path(__file__).parent / "logs" / "specialization_comparison.md"
MODES = ("baseline", "specialized")


def run(client: ClaudeClient, runs: int) -> Dict[str, List[PlanResult]]:
    """Plan every request `runs` times with each prompt. Owners get lots of time, so the
    budget never gets in the way of what is being measured."""
    owner = sample_owner(available_minutes=600)
    results: Dict[str, List[PlanResult]] = {mode: [] for mode in MODES}
    for mode in MODES:
        for n in range(1, runs + 1):
            for request in REQUESTS:
                # Retrieval off: this script measures the prompt alone (compare_rag.py
                # measures retrieval).
                result = plan_request(owner, request, client, today=date.today(),
                                      specialized=mode == "specialized", use_knowledge=False)
                results[mode].append(result)
                print(f"  {mode:<11} run {n}  {result.status:<12} {request[:55]}")
    return results


def rule_rates(results: List[PlanResult]) -> Dict[str, Tuple[int, int]]:
    checks = [c for r in results for c in check_house_rules((p.pet_name, p.task) for p in r.tasks)]
    rates = summarize(checks)
    rates["All rules"] = (sum(p for p, _ in rates.values()), sum(t for _, t in rates.values()))
    return rates


def percent(passed: int, total: int) -> str:
    return f"{passed / total:.0%} ({passed}/{total})" if total else "n/a"


def summary_rows(results: Dict[str, List[PlanResult]]) -> List[Tuple[str, str, str, str]]:
    """(rule, baseline, specialized, change) rows for the summary table."""
    base, spec = rule_rates(results["baseline"]), rule_rates(results["specialized"])
    rows = []
    for name in (*RULE_NAMES, "All rules"):
        b, s = base.get(name, (0, 0)), spec.get(name, (0, 0))
        change = (f"{(s[0] / s[1] - b[0] / b[1]) * 100:+.0f} pts" if b[1] and s[1] else "")
        rows.append((name, percent(*b), percent(*s), change))
    for label, value in (
        ("Plans with status ok", lambda rs: f"{sum(r.status == 'ok' for r in rs)}/{len(rs)}"),
        # Every request in REQUESTS is a valid pet-care request, so any refusal is a mistake.
        ("Wrongly refused", lambda rs: f"{sum(r.status == 'refused' for r in rs)}/{len(rs)}"),
        ("Average confidence", lambda rs: f"{sum(r.confidence for r in rs) / len(rs):.2f}"),
        ("Average model calls per plan", lambda rs: f"{sum(r.llm_calls for r in rs) / len(rs):.2f}"),
    ):
        rows.append((label, value(results["baseline"]), value(results["specialized"]), ""))
    return rows


def plan_rows(result: PlanResult) -> List[str]:
    """One markdown table row per proposed task, listing the house rules it breaks."""
    plan = [(p.pet_name, p.task) for p in result.tasks]
    counts = Counter((pet, t.description.lower()) for pet, t in plan)
    rows = []
    for pet, task in plan:
        broken = [c.rule for c in check_task(pet, task, counts) if not c.passed]
        rows.append(f"| {result.prompt_mode} | {pet} | {task.description} | {task.time_window()} | "
                    f"{task.duration_minutes} | {task.priority} | {task.frequency} | "
                    f"{', '.join(broken) or '—'} |")
    if not plan:
        rows.append(f"| {result.prompt_mode} | — | ({result.status}: {result.message}) | | | | | |")
    return rows


def write_report(results: Dict[str, List[PlanResult]], runs: int, model: str) -> None:
    lines = [
        "# Specialization comparison: baseline vs. house-rules prompt",
        "",
        f"Generated by `python compare_prompts.py --runs {runs}` on {date.today()} with `{model}`: "
        f"{len(REQUESTS)} requests × {runs} run(s) per prompt. The **baseline** prompt has the reply "
        "format only; the **specialized** prompt adds the PawPal+ house rules and three few-shot "
        "examples (`prompts.py`). Care-note retrieval is off for both, so only the prompt "
        "differs. Each proposed task is scored by `house_rules.check_house_rules()`.",
        "",
        "## Summary",
        "",
        "| Measure | Baseline | Specialized | Change |",
        "|---|---|---|---|",
    ]
    lines += [f"| {a} | {b} | {c} | {d} |" for a, b, c, d in summary_rows(results)]
    lines += ["", "## Side by side (run 1)", ""]
    for i, request in enumerate(REQUESTS):
        lines += [f"### \"{request}\"", "",
                  "| Prompt | Pet | Task | Time | Min | Priority | Repeats | Rules broken |",
                  "|---|---|---|---|---|---|---|---|"]
        lines += plan_rows(results["baseline"][i]) + plan_rows(results["specialized"][i]) + [""]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3, help="runs per prompt (default 3)")
    args = parser.parse_args()
    setup_logging()
    try:
        client = ClaudeClient()
    except LLMError as err:
        raise SystemExit(f"❌ {err}") from err
    print(f"Comparing prompts with {client.model}: {len(REQUESTS)} requests × {args.runs} run(s) each")
    results = run(client, args.runs)
    print(f"\n{'Measure':<30} {'Baseline':>16} {'Specialized':>16} {'Change':>9}")
    for a, b, c, d in summary_rows(results):
        print(f"{a:<30} {b:>16} {c:>16} {d:>9}")
    write_report(results, args.runs, client.model)
    print(f"\n📄 Full comparison written to {OUTPUT.relative_to(Path(__file__).parent)}")


if __name__ == "__main__":
    main()
