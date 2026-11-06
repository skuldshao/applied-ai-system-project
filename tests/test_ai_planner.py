"""Tests for the AI Planner agent loop. All offline: FakeLLM plays the model."""

from datetime import date, time

import pytest

from ai_planner import (
    MAX_FIX_ROUNDS,
    apply_plan,
    check_request,
    format_trace,
    plan_request,
    save_trace,
)
from llm_client import FakeLLM, LLMError
from pawpal_system import Owner, Pet, Task

TODAY = date(2026, 11, 5)

# --- Helpers -------------------------------------------------------------------------


@pytest.fixture
def owner():
    """An owner with two pets, 90 free minutes, and nothing scheduled yet."""
    o = Owner(name="Jordan", available_minutes=90)
    o.add_pet(Pet(name="Mochi", species="dog", age=3))
    o.add_pet(Pet(name="Luna", species="cat", age=5))
    return o


def task(desc="Walk", start="08:00", dur=30, pet="Mochi", pri="medium", freq="once"):
    """One drafted task, in the shape the model returns."""
    return {"pet_name": pet, "description": desc, "start_time": start,
            "duration_minutes": dur, "priority": pri, "frequency": freq}


def draft(*tasks, confidence=0.9, refuse=False, reason=""):
    """A full model reply, in the shape PLAN_SCHEMA requires."""
    return {"refuse": refuse, "refuse_reason": reason, "reasoning": "test reasoning",
            "tasks": list(tasks), "summary": "test summary", "confidence": confidence}


def steps(result):
    return [s.name for s in result.trace]


# --- Happy path ----------------------------------------------------------------------


def test_clean_plan_is_ok_after_one_call(owner):
    fake = FakeLLM([draft(task("Walk", "08:00", 30), task("Feed", "09:00", 10, pet="luna"))])
    result = plan_request(owner, "Walk Mochi at 8 and feed Luna at 9", fake, today=TODAY)

    assert result.status == "ok"
    assert result.llm_calls == 1 and result.fix_rounds == 0
    assert [(p.pet_name, p.task.description, p.task.start_time) for p in result.tasks] == [
        ("Mochi", "Walk", time(8, 0)), ("Luna", "Feed", time(9, 0))]  # "luna" -> canonical "Luna"
    assert result.confidence == 0.9 and result.summary == "test summary"
    assert steps(result) == ["Guard", "Retrieve", "Plan", "Validate", "Check", "Result"]


def test_on_step_sees_every_step_as_it_happens(owner):
    seen = []
    result = plan_request(owner, "Walk Mochi at 8", FakeLLM([draft(task())]), today=TODAY,
                          on_step=seen.append)
    assert seen == result.trace


def test_plan_prompt_includes_context_and_quoted_request(owner):
    owner.pets[0].add_task(Task("Breakfast", "07:00", 15, due_date=TODAY))
    fake = FakeLLM([draft(task())])
    plan_request(owner, "Walk Mochi at 8", fake, today=TODAY)
    prompt = fake.calls[0]["prompt"]
    assert "Mochi (dog, age 3)" in prompt and "Luna (cat, age 5)" in prompt
    assert "07:00-07:15 Mochi: Breakfast" in prompt
    assert "90 minutes (15 already planned, 75 left)" in prompt
    assert '"""\nWalk Mochi at 8\n"""' in prompt
    assert fake.calls[0]["schema"]["required"][0] == "refuse"


def test_planning_never_changes_the_owner_until_applied(owner):
    before = owner.to_dict()
    result = plan_request(owner, "Walk Mochi at 8", FakeLLM([draft(task())]), today=TODAY)
    assert owner.to_dict() == before
    assert apply_plan(owner, result) == 1
    assert owner.find_pet("Mochi").tasks[0].description == "Walk"


# --- Fix loop --------------------------------------------------------------------------


def test_invalid_then_conflict_then_fixed_takes_two_rounds(owner):
    # The real Haiku mistake from Step 2: meds with 0 minutes, then meds overlapping the walk.
    fake = FakeLLM([
        draft(task("Walk", "08:00", 30), task("Meds", "08:15", 0)),
        draft(task("Walk", "08:00", 30), task("Meds", "08:15", 10)),
        draft(task("Walk", "08:00", 30), task("Meds", "08:30", 10)),
    ])
    result = plan_request(owner, "Walk Mochi at 8 for 30 min, meds at 8:15", fake, today=TODAY)

    assert result.status == "ok"
    assert result.fix_rounds == 2 and result.llm_calls == 3
    assert "duration_minutes must be positive" in fake.calls[1]["prompt"]
    # The second fix prompt names the overlap and the free slot the scheduler found.
    assert "'Walk' 08:00-08:30 overlaps 'Meds' 08:15-08:25" in fake.calls[2]["prompt"]
    assert "next free slot for 'Meds' is 08:30" in fake.calls[2]["prompt"]
    assert steps(result).count("Fix") == 2 and "Revise" in steps(result)


def test_gives_up_after_max_fix_rounds(owner):
    clash = draft(task("Walk", "08:00", 30), task("Play", "08:10", 20))
    fake = FakeLLM([clash] * (MAX_FIX_ROUNDS + 1))
    result = plan_request(owner, "Walk and play with Mochi at 8", fake, today=TODAY)

    assert result.status == "needs_review"
    assert result.llm_calls == MAX_FIX_ROUNDS + 1
    assert [p.kind for p in result.problems] == ["conflict"]
    assert result.can_apply  # the owner may still approve it as-is
    assert steps(result)[-2] == "Decide"


def test_bad_json_is_retried(owner):
    fake = FakeLLM(["not json at all", draft(task())])
    result = plan_request(owner, "Walk Mochi at 8", fake, today=TODAY)
    assert result.status == "ok" and result.fix_rounds == 1
    assert "not valid JSON" in fake.calls[1]["prompt"]


def test_conflict_with_existing_task_is_reported(owner):
    owner.pets[1].add_task(Task("Vet visit", "08:00", 60, due_date=TODAY))
    fake = FakeLLM([draft(task("Walk", "08:30", 30))] * (MAX_FIX_ROUNDS + 1))
    result = plan_request(owner, "Walk Mochi at 8:30", fake, today=TODAY)
    assert result.problems[0].kind == "conflict"
    assert "next free slot for 'Walk' is 09:00" in result.problems[0].message


def test_existing_conflicts_are_not_blamed_on_the_plan(owner):
    owner.pets[0].add_task(Task("Brush", "07:00", 30, due_date=TODAY))
    owner.pets[1].add_task(Task("Comb", "07:10", 10, due_date=TODAY))  # old clash
    result = plan_request(owner, "Feed Luna at 9", FakeLLM([draft(task("Feed", "09:00", 10, pet="Luna"))]),
                          today=TODAY)
    assert result.status == "ok"


# --- Problems only the owner can decide --------------------------------------------------


def test_over_budget_stops_without_asking_the_model_again(owner):
    owner.available_minutes = 30
    fake = FakeLLM([draft(task("Walk", "08:00", 30), task("Play", "10:00", 30))])
    result = plan_request(owner, "Walk and play with Mochi", fake, today=TODAY)

    assert result.status == "needs_review"
    assert result.llm_calls == 1  # not fixable by the model, so no wasted calls
    assert [p.kind for p in result.problems] == ["over_budget"]
    assert "doesn't fit: with this plan, only 0 of the owner's 30 minutes" in result.problems[0].message


def test_plan_that_pushes_out_an_existing_task_is_flagged(owner):
    owner.available_minutes = 30
    owner.pets[0].add_task(Task("Brush", "07:00", 20, priority="medium", due_date=TODAY))
    fake = FakeLLM([draft(task("Meds", "09:00", 15, pri="high"))])
    result = plan_request(owner, "Meds for Mochi at 9", fake, today=TODAY)
    assert result.status == "needs_review"
    assert "pushes 'Brush' for Mochi out of today's schedule" in result.problems[0].message


def test_unknown_pet_keeps_valid_tasks_and_asks_the_owner(owner):
    fake = FakeLLM([draft(task("Walk"), task("Feed", "09:00", 10, pet="Rex"))])
    result = plan_request(owner, "Walk Mochi, feed Rex", fake, today=TODAY)
    assert result.status == "needs_review" and result.llm_calls == 1
    assert [p.task.description for p in result.tasks] == ["Walk"]
    assert result.problems[0].kind == "unknown_pet" and "'Rex'" in result.problems[0].message


# --- Guardrails ----------------------------------------------------------------------


@pytest.mark.parametrize("request_text, reason", [
    ("", "describe what your pet needs"),
    ("   ", "describe what your pet needs"),
    ("walk " * 200, "too long"),
    ("How much Benadryl can I give Mochi?", "can't advise on doses"),
    ("What dosage of meds for Luna", "can't advise on doses"),
    ("how many pills should Luna take", "can't advise on doses"),
])
def test_guardrail_blocks_before_any_model_call(owner, request_text, reason):
    fake = FakeLLM([])
    result = plan_request(owner, request_text, fake, today=TODAY)
    assert result.status == "refused" and reason in result.message
    assert fake.calls == []  # blocked requests cost nothing


@pytest.mark.parametrize("request_text", [
    "Give Luna her meds at 8am",
    "Walk Mochi for 30 minutes at 7",
    "How much time do I have for a walk?",
])
def test_guardrail_allows_normal_requests(owner, request_text):
    assert check_request(request_text, owner) is None


def test_no_pets_is_refused():
    assert "Add a pet first" in check_request("Walk at 8", Owner(name="Sam"))


def test_model_refusal_is_reported(owner):
    fake = FakeLLM([draft(refuse=True, reason="I can only plan pet care.")])
    result = plan_request(owner, "Write me a poem", fake, today=TODAY)
    assert result.status == "refused" and result.message == "I can only plan pet care."
    assert not result.can_apply


def test_refusal_in_a_fix_round_clears_earlier_problems(owner):
    fake = FakeLLM([draft(), draft(refuse=True, reason="Rex isn't one of your pets.")])
    result = plan_request(owner, "Feed Rex at 7am", fake, today=TODAY)
    assert result.status == "refused" and result.message == "Rex isn't one of your pets."
    assert result.problems == [] and result.tasks == [] and result.llm_calls == 2


def test_empty_plan_is_sent_back_and_then_fixed(owner):
    # The real failure evaluate.py found: the requested time was taken, so the model dropped
    # the task. The agent now asks again instead of reporting "nothing to plan".
    fake = FakeLLM([draft(), draft(task("Brushing", "10:00", 15, pet="Luna", pri="low"))])
    result = plan_request(owner, "Brush Luna at 9:30am", fake, today=TODAY)
    assert result.status == "ok" and result.fix_rounds == 1
    assert "move the task to the nearest free time" in fake.calls[1]["prompt"]
    assert "Check" not in steps(result)[:3]  # an empty plan skips the schedule check


def test_plan_still_empty_after_one_retry_is_refused(owner):
    fake = FakeLLM([draft()] * (MAX_FIX_ROUNDS + 1))
    result = plan_request(owner, "Feed Rex at 7am", fake, today=TODAY)
    assert result.status == "refused" and "couldn't find any pet-care tasks" in result.message
    assert result.problems == [] and result.llm_calls == 2  # one retry only, not MAX_FIX_ROUNDS
    assert "a pet the owner doesn't have, refuse it" in fake.calls[1]["prompt"]


def test_llm_error_becomes_error_status(owner):
    fake = FakeLLM([LLMError("Couldn't reach the Claude API.")])
    result = plan_request(owner, "Walk Mochi at 8", fake, today=TODAY)
    assert result.status == "error" and "Couldn't reach" in result.message
    assert steps(result)[-1] == "Error"
    with pytest.raises(ValueError):
        apply_plan(owner, result)


def test_confidence_is_clamped(owner):
    result = plan_request(owner, "Walk Mochi", FakeLLM([draft(task(), confidence=7)]), today=TODAY)
    assert result.confidence == 1.0


# --- Trace -----------------------------------------------------------------------------


def test_save_trace_appends_markdown_runs(owner, tmp_path):
    path = tmp_path / "trace.md"
    result = plan_request(owner, "Walk Mochi | at 8", FakeLLM([draft(task())]), today=TODAY)
    save_trace(result, path)
    save_trace(result, path)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Agent trace")
    assert text.count("## ") == 2  # one section per run
    assert "Walk Mochi \\| at 8" in text  # pipes escaped so the tables stay intact
    assert "| 2 | 📚 Retrieve |" in text and "| 3 | 🧠 Plan |" in text
    assert "**Care notes:** " in text
    assert "| Mochi | Walk | 08:00-08:30 | 30 | medium | once |" in text


def test_format_trace_lists_problems_left(owner):
    owner.available_minutes = 10
    result = plan_request(owner, "Walk Mochi", FakeLLM([draft(task())]), today=TODAY)
    assert "**Problems left for the owner:**" in format_trace(result)
