"""AI Planner: turns a plain-English request into checked PawPal+ tasks.

The agent loop, one step per trace line:
  🛡️ Guard     block empty, overly long or medication-dose requests before any model call
  🧠 Plan      Claude drafts the tasks as JSON (structured outputs)
  ✅ Validate  every task goes through Task(), so bad times, durations and pets are caught
  🔍 Check     the existing Scheduler looks for time conflicts and an overflowing time budget
  🤔 Decide    fixable problems go back to Claude; problems that need the owner stop the loop
  🔧 Fix       Claude revises the whole plan, at most MAX_FIX_ROUNDS times
  🏁 Result    the plan, any problems left, and the model's confidence

plan_request() never changes the owner's data. The caller shows the plan and calls apply_plan()
only after the owner approves it, and save_trace() records each run in logs/agent_trace.md.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from llm_client import LLMClient, LLMError
from pawpal_system import Owner, Scheduler, Task
from prompts import PLAN_SCHEMA, build_fix_prompt, build_plan_prompt, get_system_prompt

logger = logging.getLogger("pawpal.agent")

MAX_FIX_ROUNDS = 2
MAX_REQUEST_CHARS = 500
TRACE_FILE = Path(__file__).parent / "logs" / "agent_trace.md"

# Problems the model can fix by revising its plan. The rest (an unknown pet, not enough time)
# need the owner's decision, so asking the model again would only waste calls.
FIXABLE_KINDS = {"bad_json", "invalid", "conflict", "empty"}

# Found by evaluate.py: when the requested time was taken, the model sometimes dropped the task
# and returned an empty plan instead of moving it. An empty plan is sent back once (not more:
# for a pet the owner doesn't have, the model also answers with an empty plan).
EMPTY_PLAN = ("The plan has no tasks, although the request asks for something. If a requested "
              "time is already taken, move the task to the nearest free time and say so in the "
              "summary instead of dropping it. If the request is not about pet care, or is for "
              "a pet the owner doesn't have, refuse it and say why.")

# A medication-dose question needs both a question about amounts and a medicine word, so
# "Give Luna her meds at 8" passes while "How much Benadryl can I give Luna?" is blocked.
_DOSE_QUESTION = re.compile(
    r"\b(how\s+(much|many)|what\s+(dose|dosage|amount)|dosage|overdose|double\s+(the\s+)?dose)\b",
    re.IGNORECASE,
)
_MEDICINE = re.compile(
    r"\b(meds?|medicine|medication|pills?|tablets?|mg|ml|dose|ibuprofen|tylenol|"
    r"acetaminophen|advil|aspirin|benadryl|insulin)\b",
    re.IGNORECASE,
)

STATUS_ICONS = {"ok": "✅", "needs_review": "⚠️", "refused": "🛡️", "error": "❌"}


@dataclass
class Problem:
    """Something wrong with a draft plan. kind is one of: bad_json, invalid, unknown_pet,
    conflict, over_budget."""

    kind: str
    message: str


@dataclass
class ProposedTask:
    """A validated task waiting for the owner's approval, and the pet it belongs to."""

    pet_name: str
    task: Task


@dataclass
class TraceStep:
    """One line of the agent's trace, e.g. ("🔍", "Check", "No conflicts ...")."""

    icon: str
    name: str
    detail: str


@dataclass
class PlanResult:
    """Everything one planner run produced.

    status is "ok" (ready to approve), "needs_review" (approvable, but problems are left for
    the owner), "refused" (blocked by a guardrail or the model), or "error" (the model failed).
    """

    request: str
    status: str = "error"
    tasks: List[ProposedTask] = field(default_factory=list)
    problems: List[Problem] = field(default_factory=list)
    summary: str = ""
    reasoning: str = ""
    confidence: float = 0.0
    fix_rounds: int = 0
    llm_calls: int = 0
    message: str = ""
    model: str = ""
    # "specialized" (house rules + examples) or "baseline"
    prompt_mode: str = "specialized"
    trace: List[TraceStep] = field(default_factory=list)

    @property
    def can_apply(self) -> bool:
        """True if there are tasks the owner could approve."""
        return self.status in ("ok", "needs_review") and bool(self.tasks)


# --- Guard ---------------------------------------------------------------------------


def check_request(request: str, owner: Owner) -> Optional[str]:
    """Input guardrail: return why a request must be blocked, or None if it may go to the model.

    Runs before any model call, so blocked requests cost nothing.
    """
    text = (request or "").strip()
    if not text:
        return "Please describe what your pet needs, for example 'Walk Mochi at 8am for 30 minutes'."
    if len(text) > MAX_REQUEST_CHARS:
        return f"That request is too long ({len(text)} characters). Please keep it under {MAX_REQUEST_CHARS}."
    if _DOSE_QUESTION.search(text) and _MEDICINE.search(text):
        return ("I can schedule medication your vet has prescribed, but I can't advise on doses. "
                "Please ask your vet.")
    if not owner.pets:
        return "Add a pet first, so I know who the tasks are for."
    return None


# --- Validate --------------------------------------------------------------------------


def parse_reply(reply: str) -> Dict[str, Any]:
    """Turn the model's reply into a dict.

    Raises:
        ValueError: If the reply isn't JSON or has no "tasks" list.
    """
    data = json.loads(reply)  # json.JSONDecodeError is a ValueError
    if not isinstance(data, dict) or not isinstance(data.get("tasks"), list):
        raise ValueError("expected a JSON object with a 'tasks' list")
    return data


def validate_draft(
    draft: Dict[str, Any], owner: Owner, today: date
) -> Tuple[List[ProposedTask], List[Problem]]:
    """Build a real Task from each drafted task; collect a Problem for each one that fails.

    Task() already rejects bad times ("25:00"), durations (0) and priorities, so the same rules
    that protect the rest of PawPal+ also check the model's output.
    """
    proposals: List[ProposedTask] = []
    problems: List[Problem] = []
    for number, item in enumerate(draft["tasks"], start=1):
        name = str(item.get("description", "")).strip() or f"task {number}"
        pet = owner.find_pet(str(item.get("pet_name", "")))
        if pet is None:
            pets = ", ".join(p.name for p in owner.pets)
            problems.append(Problem(
                "unknown_pet",
                f"'{name}' is for '{item.get('pet_name')}', who isn't one of the owner's pets ({pets})."))
            continue
        try:
            task = Task(
                description=name,
                start_time=item.get("start_time"),
                duration_minutes=int(item.get("duration_minutes")),
                priority=item.get("priority", "medium"),
                frequency=item.get("frequency", "once"),
                due_date=today,
            )
        except (TypeError, ValueError) as err:
            problems.append(
                Problem("invalid", f"'{name}' was rejected: {err}."))
            continue
        proposals.append(ProposedTask(pet.name, task))
    return proposals, problems


# --- Check -----------------------------------------------------------------------------


def _key(pet_name: str, task: Task) -> Tuple[str, str, Any]:
    return (pet_name, task.description, task.start_time)


def check_schedule(owner: Owner, proposals: List[ProposedTask], today: date) -> List[Problem]:
    """Try the proposed tasks on a copy of the owner's data and report what goes wrong.

    Uses the same Scheduler as the rest of the app: find_conflicts() for overlaps (with the
    next free slot as a hint), and the greedy time budget for tasks that don't fit today.
    Conflicts only between tasks that already existed are not reported; they aren't this
    plan's fault.
    """
    trial = Owner.from_dict(
        owner.to_dict())  # a deep copy; the real owner is never touched
    new_tasks: Dict[int, Task] = {}
    for proposal in proposals:
        copy = replace(proposal.task)
        trial.find_pet(proposal.pet_name).add_task(copy)
        new_tasks[id(copy)] = copy
    scheduler = Scheduler(trial)
    problems: List[Problem] = []

    for (_, a), (_, b) in scheduler.find_conflicts(today):
        if id(a) not in new_tasks and id(b) not in new_tasks:
            continue
        # suggest moving a new task, never an old one
        mover = b if id(b) in new_tasks else a
        slot = scheduler.find_next_available_slot(
            mover.duration_minutes, earliest=mover.start_time, today=today, ignore=mover)
        hint = (f" The next free slot for '{mover.description}' is {slot:%H:%M}."
                if slot else f" There is no free slot for '{mover.description}' later today.")
        problems.append(Problem(
            "conflict",
            f"'{a.description}' {a.time_window()} overlaps '{b.description}' {b.time_window()}.{hint}"))

    planned = scheduler.todays_schedule(today)
    left = trial.available_minutes - \
        sum(t.duration_minutes for _, t in planned)
    before = {_key(p.name, t)
              for p, t in Scheduler(owner).todays_schedule(today)}
    for pet, task in scheduler.skipped_tasks(today):
        if id(task) in new_tasks:
            problems.append(Problem(
                "over_budget",
                f"'{task.description}' ({task.duration_minutes} min) doesn't fit: with this "
                f"plan, only {left} of the owner's {trial.available_minutes} minutes are left "
                "today."))
        elif _key(pet.name, task) in before:
            problems.append(Problem(
                "over_budget",
                f"Adding this plan pushes '{task.description}' for {pet.name} out of today's "
                f"schedule (not enough time)."))
    return problems


# --- The agent loop --------------------------------------------------------------------


def plan_request(
    owner: Owner,
    request: str,
    client: LLMClient,
    today: Optional[date] = None,
    max_fix_rounds: int = MAX_FIX_ROUNDS,
    specialized: bool = True,
    on_step: Optional[Callable[[TraceStep], None]] = None,
) -> PlanResult:
    """Plan → validate → check → fix, until the plan is clean or only the owner can decide.

    Args:
        owner: The owner whose pets and schedule the plan is for. Not modified.
        request: What the owner typed, e.g. "Walk Mochi at 8am for 30 minutes".
        client: A ClaudeClient, or a FakeLLM in tests.
        today: The day to plan for. Defaults to date.today().
        max_fix_rounds: How many times the model may revise its plan.
        specialized: True (the default) sends the house rules and few-shot examples;
            False sends the baseline prompt, for comparison.
        on_step: Called with each TraceStep as soon as it happens, so a UI can show the
            agent's progress live instead of waiting for the whole run.

    Returns:
        A PlanResult with the proposed tasks, any problems left, and the full trace.
    """
    today = today or date.today()
    result = PlanResult(request=request, model=getattr(client, "model", "unknown"),
                        prompt_mode="specialized" if specialized else "baseline")
    system_prompt = get_system_prompt(specialized)

    def step(icon: str, name: str, detail: str) -> None:
        trace_step = TraceStep(icon, name, detail)
        result.trace.append(trace_step)
        logger.info("%s %s: %s", icon, name, detail)
        if on_step is not None:
            on_step(trace_step)

    blocked = check_request(request, owner)
    if blocked:
        step("🛡️", "Guard", f"Blocked before calling the model. {blocked}")
        result.status, result.message = "refused", blocked
        return result
    step("🛡️", "Guard", "Request passed the input checks.")

    request = request.strip()
    prompt = build_plan_prompt(owner, request, today)
    try:
        while True:
            reply = client.complete(system_prompt, prompt, PLAN_SCHEMA)
            result.llm_calls += 1
            label = "Plan" if result.fix_rounds == 0 else "Revise"
            try:
                draft = parse_reply(reply)
            except ValueError as err:
                step("🧠", label, f"The reply was not usable JSON ({err}).")
                proposals = []
                problems = [
                    Problem("bad_json", "Your reply was not valid JSON with a 'tasks' list.")]
            else:
                if draft.get("refuse"):
                    reason = draft.get(
                        "refuse_reason") or "This isn't something PawPal+ can plan."
                    step("🛡️", "Model refused", reason)
                    result.status, result.message = "refused", reason
                    result.tasks, result.problems = [], []  # drop anything from earlier rounds
                    return result
                result.summary = str(draft.get("summary", ""))
                result.reasoning = str(draft.get("reasoning", ""))
                result.confidence = _clamp(draft.get("confidence"))
                step("🧠", label,
                     f"{len(draft['tasks'])} task(s) drafted, confidence {result.confidence:.2f}. "
                     f"Reasoning: {result.reasoning}")
                proposals, problems = validate_draft(draft, owner, today)
                if draft["tasks"]:
                    step("✅", "Validate", f"{len(proposals)} task(s) valid, {len(problems)} "
                         "rejected." + _list_messages(problems))
                else:
                    problems.append(Problem("empty", EMPTY_PLAN))
                    step("✅", "Validate", EMPTY_PLAN)
                if proposals:  # nothing to check in an empty plan
                    schedule_problems = check_schedule(owner, proposals, today)
                    problems += schedule_problems
                    step("🔍", "Check", "No conflicts, and everything fits in today's time."
                         if not schedule_problems
                         else f"{len(schedule_problems)} issue(s)."
                         + _list_messages(schedule_problems))

            result.tasks, result.problems = proposals, problems
            if not problems:
                break
            fixable = [p for p in problems if p.kind in FIXABLE_KINDS]
            if not fixable:
                step("🤔", "Decide", "The remaining problems need the owner's decision, so stop "
                     "and show them instead of asking the model again.")
                break
            if result.fix_rounds >= 1 and all(p.kind == "empty" for p in problems):
                step("🤔", "Decide", "The plan is still empty after asking again, so there is "
                     "nothing to plan.")
                break
            if result.fix_rounds >= max_fix_rounds:
                step("🤔", "Decide", f"Still {len(problems)} problem(s) after {max_fix_rounds} fix "
                     "round(s), so stop and show them to the owner.")
                break
            result.fix_rounds += 1
            step("🔧", "Fix", f"Round {result.fix_rounds} of {max_fix_rounds}: {len(fixable)} "
                 "fixable problem(s), so send the plan and the problems back to the model.")
            prompt = build_fix_prompt(owner, request, reply, [
                                      p.message for p in problems], today)
    except LLMError as err:
        step("❌", "Error", str(err))
        result.status, result.message = "error", str(err)
        return result

    if not result.tasks and all(p.kind == "empty" for p in result.problems):
        # Still empty after the fix rounds (or empty with no fix allowed): nothing to plan.
        result.status, result.problems = "refused", []
        result.message = "I couldn't find any pet-care tasks in that request."
    else:
        result.status = "ok" if not result.problems else "needs_review"
    step(STATUS_ICONS[result.status], "Result",
         f"{result.status}: {len(result.tasks)} task(s), {len(result.problems)} problem(s) left, "
         f"{result.llm_calls} model call(s).")
    return result


def apply_plan(owner: Owner, result: PlanResult) -> int:
    """Add an approved plan's tasks to the owner's pets. Call only after the owner approves.

    Returns:
        How many tasks were added.

    Raises:
        ValueError: If the result has nothing that can be applied.
    """
    if not result.can_apply:
        raise ValueError(f"Nothing to apply (status: {result.status}).")
    for proposal in result.tasks:
        owner.find_pet(proposal.pet_name).add_task(proposal.task)
    logger.info("Applied %d task(s) for request %r",
                len(result.tasks), result.request)
    return len(result.tasks)


# --- Trace file ------------------------------------------------------------------------


def save_trace(result: PlanResult, path: Union[str, Path] = TRACE_FILE) -> Path:
    """Append one run to the markdown trace file (logs/agent_trace.md by default).

    Each run gets its request, every step the agent took, and the final plan, so the
    agent's intermediate reasoning is kept as a committed record, not just terminal output.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with open(path, "a", encoding="utf-8") as f:
        if new_file:
            f.write("# Agent trace\n\nEvery AI Planner run, step by step. "
                    "Written by `ai_planner.save_trace()`.\n\n")
        f.write(format_trace(result))
    return path


def format_trace(result: PlanResult) -> str:
    """Render one run as markdown: a header, a step table, the plan and any problems left."""
    icon = STATUS_ICONS.get(result.status, "")
    lines = [
        f"## {datetime.now():%Y-%m-%d %H:%M} · {icon} {result.status}",
        "",
        f"**Request:** {_cell(result.request)}  ",
        f"**Model:** {result.model} · **Prompt:** {result.prompt_mode} · "
        f"**Model calls:** {result.llm_calls} · "
        f"**Fix rounds:** {result.fix_rounds} · **Confidence:** {result.confidence:.2f}",
        "",
        "| # | Step | What happened |",
        "|---|------|---------------|",
    ]
    lines += [f"| {n} | {s.icon} {s.name} | {_cell(s.detail)} |"
              for n, s in enumerate(result.trace, start=1)]
    if result.tasks:
        lines += ["", "**Proposed tasks**", "",
                  "| Pet | Task | Time | Minutes | Priority | Repeats |",
                  "|---|---|---|---|---|---|"]
        lines += [f"| {p.pet_name} | {_cell(p.task.description)} | {p.task.time_window()} | "
                  f"{p.task.duration_minutes} | {p.task.priority} | {p.task.frequency} |"
                  for p in result.tasks]
    if result.summary:
        lines += ["", f"**Summary:** {_cell(result.summary)}"]
    if result.message:
        lines += ["", f"**Message:** {_cell(result.message)}"]
    if result.problems:
        lines += ["", "**Problems left for the owner:**"]
        lines += [f"- {_cell(p.message)}" for p in result.problems]
    lines += ["", "---", ""]
    return "\n".join(lines) + "\n"


# --- Small helpers ---------------------------------------------------------------------


def _clamp(value: Any) -> float:
    """Keep the model's confidence between 0 and 1; anything that isn't a number counts as 0."""
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _list_messages(problems: List[Problem]) -> str:
    return "".join(f" {p.message}" for p in problems)


def _cell(text: str) -> str:
    """Make text safe for one markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ")
