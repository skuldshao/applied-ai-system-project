"""PawPal+ house rules: the care conventions the specialized prompt teaches the model.

One table (HOUSE_RULES) drives both sides:
- prompts.py turns it into the rules text that is sent to Claude, and
- check_house_rules() scores a plan against it, so the baseline and specialized prompts can be
  compared with numbers (see compare_prompts.py).

Why these rules: task names are how PawPal+ finds and removes tasks (Pet.find_task and
Pet.remove_task match by description), so two tasks called "Feed Luna" are a real bug risk;
the app already shows the pet next to every task, so a pet name in the task name is noise; and
the greedy daily plan drops low-priority tasks first, so medication and meals must be high.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

from pawpal_system import Task


@dataclass(frozen=True)
class CareRule:
    """The house standard for one kind of care task."""

    category: str
    keywords: Tuple[str, ...]  # matched against the lowercased task name
    duration: int  # minutes, used when the owner doesn't give a duration
    priority: str
    daily: bool  # repeats daily unless the owner says it's a one-time thing


# Checked in order, so medication comes before meal ("Pill with breakfast" is medication).
HOUSE_RULES: Tuple[CareRule, ...] = (
    CareRule("medication", ("medication", "medicine", "meds", "pill", "drops", "insulin"), 5, "high", True),
    CareRule("vet visit", ("vet", "checkup", "check-up"), 60, "high", False),
    CareRule("meal", ("breakfast", "dinner", "lunch", "meal", "feed", "food"), 10, "high", True),
    CareRule("walk", ("walk",), 30, "medium", False),
    CareRule("grooming", ("brush", "groom", "nail", "bath", "teeth"), 15, "low", False),
    CareRule("play", ("play", "fetch", "train"), 20, "low", False),
    CareRule("cleaning", ("litter", "clean", "cage", "tank"), 10, "low", False),
)

# The rules check_house_rules() scores, in the order reports show them.
NO_PET_NAME = "No pet name in task name"
UNIQUE_NAME = "Unique task name per pet"
PRIORITY = "House priority"
DURATION = "House duration"
DAILY = "Meals & meds repeat daily"
RULE_NAMES = (NO_PET_NAME, UNIQUE_NAME, PRIORITY, DURATION, DAILY)


@dataclass
class RuleCheck:
    """The result of checking one house rule on one task."""

    rule: str
    pet_name: str
    task: str
    passed: bool
    expected: str
    got: str


def classify(description: str) -> Optional[CareRule]:
    """Return the house rule for a task name, or None if it isn't a known kind of care."""
    text = description.lower()
    return next((rule for rule in HOUSE_RULES if any(k in text for k in rule.keywords)), None)


def rules_text() -> str:
    """The house rules as plain text for the specialized system prompt."""
    lines = [
        "PawPal+ house rules (follow them unless the owner asks for something different):",
        "- Name each task with a short label and never include the pet's name, because the app "
        'already shows it: "Breakfast", not "Feed Luna".',
        "- Give each of a pet's tasks a different name: two meals are \"Breakfast\" and "
        '"Dinner", two walks are "Morning walk" and "Evening walk".',
        "- If the owner gives no duration, use the house duration. Always use the house priority:",
    ]
    for rule in HOUSE_RULES:
        repeats = ", repeats daily" if rule.daily else ""
        lines.append(f"  - {rule.category} ({', '.join(rule.keywords)}): "
                     f"{rule.duration} min, {rule.priority} priority{repeats}")
    lines += [
        "- Meals and medication repeat daily unless the owner says it is a one-time thing.",
        "- If no time is given, choose a sensible one (mornings around 08:00, evenings around "
        "18:00) that doesn't overlap other tasks.",
    ]
    return "\n".join(lines)


def check_task(
    pet_name: str, task: Task, name_counts: Counter, check_durations: bool = True
) -> List[RuleCheck]:
    """Check one task against every house rule that applies to it.

    Args:
        pet_name: The pet the task is for.
        task: The proposed task.
        name_counts: How many proposed tasks each (pet, lowercased name) has, for the
            unique-name rule.
        check_durations: False when the owner gave durations themselves, so the house
            duration doesn't apply.
    """

    def check(rule: str, passed: bool, expected: str, got: str) -> RuleCheck:
        return RuleCheck(rule, pet_name, task.description, passed, expected, got)

    has_pet_name = re.search(rf"\b{re.escape(pet_name)}\b", task.description, re.IGNORECASE)
    checks = [
        check(NO_PET_NAME, not has_pet_name, f"no '{pet_name}'", task.description),
        check(UNIQUE_NAME, name_counts[(pet_name, task.description.lower())] == 1,
              "used once", f"used {name_counts[(pet_name, task.description.lower())]}x"),
    ]
    rule = classify(task.description)
    if rule is not None:
        checks.append(check(PRIORITY, task.priority == rule.priority, rule.priority, task.priority))
        if check_durations:
            checks.append(check(DURATION, task.duration_minutes == rule.duration,
                                f"{rule.duration} min", f"{task.duration_minutes} min"))
        if rule.daily:
            checks.append(check(DAILY, task.frequency == "daily", "daily", task.frequency))
    return checks


def check_house_rules(
    plan: Iterable[Tuple[str, Task]], check_durations: bool = True
) -> List[RuleCheck]:
    """Check every task in a plan against the house rules.

    Args:
        plan: (pet_name, task) pairs, e.g. [(p.pet_name, p.task) for p in result.tasks].
        check_durations: False when the request gave its own durations.

    Returns:
        One RuleCheck per rule that applies to each task.
    """
    plan = list(plan)
    counts = Counter((pet, task.description.lower()) for pet, task in plan)
    return [c for pet, task in plan for c in check_task(pet, task, counts, check_durations)]


def summarize(checks: Iterable[RuleCheck]) -> Dict[str, Tuple[int, int]]:
    """Count (passed, total) for each rule, in RULE_NAMES order. Rules never checked are left out."""
    totals: Dict[str, List[int]] = {name: [0, 0] for name in RULE_NAMES}
    for c in checks:
        totals[c.rule][0] += c.passed
        totals[c.rule][1] += 1
    return {name: (passed, total) for name, (passed, total) in totals.items() if total}
