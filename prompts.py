"""What the AI Planner says to Claude: the system prompt, the JSON schema, and the prompt builders.

ai_planner.py owns the logic and this file owns the wording, so prompt versions can be
compared without touching the agent loop.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict, List

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

SYSTEM_PROMPT = """\
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
