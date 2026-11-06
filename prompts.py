"""What the AI Planner says to Claude: the system prompts, the JSON schema, and the prompt builders.

ai_planner.py owns the logic and this file owns the wording, so prompt versions can be
compared without touching the agent loop. There are two system prompts:

- BASELINE_SYSTEM_PROMPT: the reply format and basic rules only.
- SPECIALIZED_SYSTEM_PROMPT: the baseline plus the PawPal+ house rules (house_rules.py) and
  three worked few-shot examples. compare_prompts.py measures the difference.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List

from house_rules import rules_text
from pawpal_system import Owner, Scheduler

# The reply format, enforced by the API (structured outputs). Field order matters: the model
# writes "refuse" first, then its reasoning, and only then the tasks.
PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "refuse": {"type": "boolean"},
        "refuse_reason": {"type": "string"},
        "reasoning": {"type": "string"},
        "tasks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pet_name": {"type": "string"},
                    "description": {"type": "string"},
                    "start_time": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "priority": {"type": "string", "enum": ["low", "medium", "high"]},
                    "frequency": {"type": "string", "enum": ["once", "daily", "weekly"]},
                },
                "required": [
                    "pet_name", "description", "start_time",
                    "duration_minutes", "priority", "frequency",
                ],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["refuse", "refuse_reason", "reasoning", "tasks", "summary", "confidence"],
    "additionalProperties": False,
}

BASELINE_SYSTEM_PROMPT = """\
You are PawPal+, a planning assistant that turns a pet owner's request into scheduled pet-care tasks.

Reply with JSON that matches the schema:
- refuse: true only if the request is not about scheduling pet care, or asks for medical advice \
such as how much medicine to give. Then explain why in refuse_reason and return no tasks. \
Otherwise refuse is false and refuse_reason is "".
- reasoning: one to three short sentences on how you chose the times, durations and priorities.
- tasks: one entry per care activity. pet_name must be one of the owner's pets. start_time is \
24-hour "HH:MM". duration_minutes is a whole number of minutes, at least 1. priority is low, \
medium or high. frequency is once, daily or weekly.
- summary: one friendly sentence describing the plan to the owner.
- confidence: a number from 0.0 to 1.0 for how sure you are that the plan matches the request.

Never invent pets. Avoid times that overlap what is already scheduled today.\
"""


def _task(pet: str, description: str, start: str, minutes: int, priority: str, frequency: str):
    return {"pet_name": pet, "description": description, "start_time": start,
            "duration_minutes": minutes, "priority": priority, "frequency": frequency}


# Worked examples that show the house rules in action. They use made-up pets (Biscuit, Pepper)
# so the model copies the pattern, not the pets. tests/test_house_rules.py checks that every
# example follows the house rules, so the examples can't drift from the rules table.
FEW_SHOT_EXAMPLES: List[Dict[str, Any]] = [
    {
        "context": "Pets: Biscuit (dog, age 4). Already scheduled today: nothing yet.",
        "request": "Feed Biscuit at 7 and 6pm, and give him his allergy pill with breakfast",
        "reply": {
            "refuse": False, "refuse_reason": "",
            "reasoning": "Meals and medication are routine, so they repeat daily with the house "
                         "durations and high priority. The pill goes right after breakfast so "
                         "the two don't overlap.",
            "tasks": [
                _task("Biscuit", "Breakfast", "07:00", 10, "high", "daily"),
                _task("Biscuit", "Allergy pill", "07:10", 5, "high", "daily"),
                _task("Biscuit", "Dinner", "18:00", 10, "high", "daily"),
            ],
            "summary": "Biscuit gets breakfast at 7:00 with his allergy pill right after, and "
                       "dinner at 18:00, every day.",
            "confidence": 0.95,
        },
    },
    {
        "context": "Pets: Biscuit (dog, age 4), Pepper (cat, age 2). "
                   "Already scheduled today: 07:00-07:10 Biscuit: Breakfast.",
        "request": "Walk Biscuit in the morning and brush Pepper this evening",
        "reply": {
            "refuse": False, "refuse_reason": "",
            "reasoning": "No times or durations were given, so the walk takes the house 30 "
                         "minutes at 08:00, after breakfast, and brushing takes 15 minutes at "
                         "18:00. Neither is routine, so both happen once.",
            "tasks": [
                _task("Biscuit", "Morning walk", "08:00", 30, "medium", "once"),
                _task("Pepper", "Brushing", "18:00", 15, "low", "once"),
            ],
            "summary": "Biscuit's walk is at 8:00 and Pepper gets brushed at 18:00.",
            "confidence": 0.85,
        },
    },
    {
        "context": "Pets: Pepper (cat, age 2). Already scheduled today: nothing yet.",
        "request": "Clean Pepper's litter box every night at 9 and play with her before that",
        "reply": {
            "refuse": False, "refuse_reason": "",
            "reasoning": "The owner asked for the litter box every night, so it repeats daily "
                         "at 21:00 for the house 10 minutes. Play takes the house 20 minutes "
                         "and ends at 20:50, before the litter box.",
            "tasks": [
                _task("Pepper", "Playtime", "20:30", 20, "low", "once"),
                _task("Pepper", "Litter box", "21:00", 10, "low", "daily"),
            ],
            "summary": "Pepper plays at 20:30 and her litter box is cleaned at 21:00 every night.",
            "confidence": 0.9,
        },
    },
]


def _examples_text() -> str:
    parts = []
    for number, example in enumerate(FEW_SHOT_EXAMPLES, start=1):
        parts.append(
            f"Example {number}\n{example['context']}\n"
            f'Owner\'s request:\n"""\n{example["request"]}\n"""\n'
            f"Reply:\n{json.dumps(example['reply'])}"
        )
    return "\n\n".join(parts)


SPECIALIZED_SYSTEM_PROMPT = (
    f"{BASELINE_SYSTEM_PROMPT}\n\n{rules_text()}\n\n"
    "Examples (these use made-up pets; only ever plan for the owner's real pets):\n\n"
    f"{_examples_text()}"
)


def get_system_prompt(specialized: bool = True) -> str:
    """Return the specialized prompt (house rules + few-shot examples) or the baseline one."""
    return SPECIALIZED_SYSTEM_PROMPT if specialized else BASELINE_SYSTEM_PROMPT


def describe_context(owner: Owner, today: date) -> str:
    """Describe the owner, their pets, their time budget and today's schedule for the model."""
    schedule = Scheduler(owner).todays_schedule(today)
    used = sum(task.duration_minutes for _, task in schedule)
    pets = ", ".join(f"{p.name} ({p.species}, age {p.age})" for p in owner.pets) or "none"
    lines = [
        f"Today is {today:%A %Y-%m-%d}.",
        f"Owner: {owner.name}. Time available today: {owner.available_minutes} minutes "
        f"({used} already planned, {owner.available_minutes - used} left).",
        f"Pets: {pets}.",
        "Already scheduled today:",
    ]
    lines += [f"- {task.time_window()} {pet.name}: {task.description}" for pet, task in schedule]
    if not schedule:
        lines.append("- nothing yet")
    return "\n".join(lines)


def _quoted_request(request: str) -> str:
    # Triple quotes mark where the owner's words start and stop, so they read as data.
    return f'Owner\'s request:\n"""\n{request}\n"""'


def build_plan_prompt(owner: Owner, request: str, today: date) -> str:
    """Build the first prompt: context plus the owner's request."""
    return f"{describe_context(owner, today)}\n\n{_quoted_request(request)}\n\nPlan the tasks for this request."


def build_fix_prompt(
    owner: Owner, request: str, previous_reply: str, problems: List[str], today: date
) -> str:
    """Build a fix prompt: the earlier draft plus the problems the scheduler found in it.

    Each fix is a fresh request that carries everything the model needs, so no chat history
    is kept between calls.
    """
    problem_lines = "\n".join(f"- {message}" for message in problems)
    return (
        f"{describe_context(owner, today)}\n\n{_quoted_request(request)}\n\n"
        f"Your previous plan:\n{previous_reply}\n\n"
        f"The PawPal+ scheduler checked that plan and found these problems:\n{problem_lines}\n\n"
        "Return the complete corrected plan (every task, not only the changed ones). "
        "Change only what is needed to fix the problems. If a problem can only be solved by "
        "dropping or shortening something the owner asked for (for example, not enough time "
        "today), keep the task and explain it in the summary."
    )
