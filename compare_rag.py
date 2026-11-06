"""Measure what retrieval (RAG) changes: the same requests planned with and without care notes.

Each case is a request where one note in knowledge/ should change the plan, plus an automatic
check for that change. Both sides use the specialized prompt; only retrieval is switched on or
off. Prints a summary and writes logs/rag_comparison.md.

    python compare_rag.py            # 3 runs per side (30 Haiku calls, a few cents)
    python compare_rag.py --runs 1
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional

from ai_planner import PlanResult, ProposedTask, plan_request
from house_rules import classify
from llm_client import ClaudeClient, LLMError
from pawpal_logging import setup_logging
from pawpal_system import Owner, Pet, Task
from sample_data import sample_owner

OUTPUT = Path(__file__).parent / "logs" / "rag_comparison.md"
SIDES = ("without", "with")  # retrieval off, retrieval on


def _named(result: PlanResult, pet: str, word: str) -> List[ProposedTask]:
    """The proposed tasks for a pet whose name contains a word, e.g. Rocky's walks."""
    return [p for p in result.tasks if p.pet_name == pet and word in p.task.description.lower()]


def _meals(result: PlanResult, owner: Owner, pet: str) -> List[Task]:
    """A pet's meals: the ones already scheduled plus the ones in the plan."""
    existing = [t for t in owner.find_pet(pet).tasks]
    planned = [p.task for p in result.tasks if p.pet_name == pet]
    return [t for t in existing + planned if (rule := classify(t.description)) and rule.category == "meal"]


def senior_walks_are_short(result: PlanResult, owner: Owner) -> bool:
    walks = _named(result, "Rocky", "walk")
    return bool(walks) and all(p.task.duration_minutes <= 20 for p in walks)


def walk_waits_after_meal(result: PlanResult, owner: Owner) -> bool:
    walks, meals = _named(result, "Mochi", "walk"), _meals(result, owner, "Mochi")
    for walk in walks:
        before = [m.end_minute for m in meals if m.end_minute <= walk.task.start_minute]
        if before and walk.task.start_minute - max(before) < 50:  # "about an hour"
            return False
    return bool(walks)


def insulin_follows_meals(result: PlanResult, owner: Owner) -> bool:
    shots, meals = _named(result, "Luna", "insulin"), _meals(result, owner, "Luna")
    return bool(shots) and all(
        any(0 <= p.task.start_minute - m.end_minute <= 15 for m in meals) for p in shots)


def no_midday_walks(result: PlanResult, owner: Owner) -> bool:
    walks = _named(result, "Mochi", "walk")
    return bool(walks) and all(not 12 * 60 <= p.task.start_minute < 16 * 60 for p in walks)


def litter_is_daily(result: PlanResult, owner: Owner) -> bool:
    boxes = _named(result, "Luna", "litter")
    return bool(boxes) and all(p.task.frequency == "daily" for p in boxes)


def _luna_meals(owner: Owner) -> None:
    luna = owner.find_pet("Luna")
    luna.add_task(Task("Breakfast", "08:00", 10, "high", "daily"))
    luna.add_task(Task("Dinner", "18:00", 10, "high", "daily"))


@dataclass
class RagCase:
    """A request, the care note that should change its plan, and a check for that change."""

    request: str
    note: str
    rule: str
    check: Callable[[PlanResult, Owner], bool]
    setup: Optional[Callable[[Owner], None]] = None

    def make_owner(self) -> Owner:
        """Mochi (dog, 3), Luna (cat, 5) and Rocky (dog, 12), plus this case's setup."""
        owner = sample_owner(available_minutes=600)
        owner.add_pet(Pet(name="Rocky", species="dog", age=12))
        if self.setup:
            self.setup(owner)
        return owner


CASES = [
    RagCase("Take Rocky for a walk every morning and evening", "Walks for senior dogs",
            "Rocky is 12: each walk is 20 minutes or less (house default: 30)",
            senior_walks_are_short),
    RagCase("Feed Mochi at 7am and take him for a walk after breakfast", "Exercise after meals",
            "the walk starts about an hour after breakfast ends", walk_waits_after_meal),
    RagCase("Luna needs her insulin twice a day", "Insulin for diabetic pets",
            "each insulin task starts within 15 min after one of Luna's meals (08:00, 18:00)",
            insulin_follows_meals, setup=_luna_meals),
    RagCase("Walk Mochi this afternoon", "Walks in hot weather",
            "the walk does not start between 12:00 and 16:00", no_midday_walks),
    RagCase("Clean Luna's litter box", "Litter box",
            "scooping repeats daily (house default for cleaning: once)", litter_is_daily),
]


def run(client: ClaudeClient, runs: int) -> Dict[str, List[List[PlanResult]]]:
    """For each side, a list per case of its runs."""
    results: Dict[str, List[List[PlanResult]]] = {side: [] for side in SIDES}
    for side in SIDES:
        for case in CASES:
            case_runs = []
            for _ in range(runs):
                owner = case.make_owner()
                case_runs.append(plan_request(owner, case.request, client,
                                              use_knowledge=side == "with"))
            results[side].append(case_runs)
            passed = sum(case.check(r, case.make_owner()) for r in case_runs)
            print(f"  {side:<8} retrieval  {passed}/{runs} follow the note  {case.request[:50]}")
    return results


def passes(case: RagCase, case_runs: List[PlanResult]) -> int:
    return sum(case.check(r, case.make_owner()) for r in case_runs)


def task_list(result: PlanResult) -> str:
    if not result.tasks:
        return f"({result.status}) {result.message}".strip()
    return "; ".join(f"{p.pet_name} {p.task.description} {p.task.time_window()} "
                     f"({p.task.duration_minutes} min, {p.task.frequency})" for p in result.tasks)


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def write_report(results: Dict[str, List[List[PlanResult]]], runs: int, model: str) -> None:
    total = {side: sum(passes(c, r) for c, r in zip(CASES, results[side])) for side in SIDES}
    n = len(CASES) * runs
    lines = [
        "# RAG comparison: planning with and without retrieved care notes",
        "",
        f"Generated by `python compare_rag.py --runs {runs}` on {date.today()} with `{model}`: "
        f"{len(CASES)} requests × {runs} run(s) per side. Both sides use the specialized prompt; "
        "**with** retrieval, `retriever.py` finds the notes in `knowledge/` that match the request "
        "and the named pets' species and life stage, and puts them in the prompt. Each plan is "
        "checked automatically for the behaviour its care note asks for. The owner has Mochi "
        "(dog, 3), Luna (cat, 5) and Rocky (dog, 12).",
        "",
        "## Summary",
        "",
        "| Request | Care note that should change the plan | Rule checked | Without retrieval | With retrieval |",
        "|---|---|---|---|---|",
    ]
    for i, case in enumerate(CASES):
        lines.append(f"| \"{_cell(case.request)}\" | {case.note} | {_cell(case.rule)} | "
                     f"{passes(case, results['without'][i])}/{runs} | "
                     f"{passes(case, results['with'][i])}/{runs} |")
    lines.append(f"| **All** | | | **{total['without']}/{n} ({total['without'] / n:.0%})** | "
                 f"**{total['with']}/{n} ({total['with'] / n:.0%})** |")
    lines += ["", "## Before and after (run 1)", ""]
    for i, case in enumerate(CASES):
        without, with_ = results["without"][i][0], results["with"][i][0]
        lines += [
            f"### \"{case.request}\"", "",
            f"- **Notes retrieved:** {'; '.join(with_.notes) or 'none'}",
            f"- **Without retrieval** ({'✅' if case.check(without, case.make_owner()) else '❌'}): "
            f"{_cell(task_list(without))}",
            f"- **With retrieval** ({'✅' if case.check(with_, case.make_owner()) else '❌'}): "
            f"{_cell(task_list(with_))}",
            f"- **Model's reasoning with retrieval:** {_cell(with_.reasoning or with_.message)}",
            "",
        ]
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runs", type=int, default=3, help="runs per side (default 3)")
    args = parser.parse_args()
    setup_logging()
    try:
        client = ClaudeClient()
    except LLMError as err:
        raise SystemExit(f"❌ {err}") from err
    print(f"Comparing planning with and without retrieval ({client.model}): "
          f"{len(CASES)} requests × {args.runs} run(s) per side")
    results = run(client, args.runs)
    n = len(CASES) * args.runs
    for side in SIDES:
        total = sum(passes(c, r) for c, r in zip(CASES, results[side]))
        print(f"\n{side.capitalize():<8} retrieval: {total}/{n} plans follow the care note ({total / n:.0%})", end="")
    write_report(results, args.runs, client.model)
    print(f"\n\n📄 Full comparison written to {OUTPUT.relative_to(Path(__file__).parent)}")


if __name__ == "__main__":
    main()
