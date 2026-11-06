"""Tests for evaluate.py: the expectations, the runner and the report. Offline (FakeLLM)."""

from ai_planner import PlanResult, Problem, ProposedTask
from evaluate import CASES, EvalCase, expect, run_case, write_report
from llm_client import FakeLLM
from pawpal_system import Task
from sample_data import sample_owner


def plan(status="ok", calls=1, tasks=(), problems=()):
    """A hand-built PlanResult, so each expectation can be tested without a model."""
    return PlanResult(request="r", status=status, llm_calls=calls, tasks=list(tasks),
                      problems=list(problems), confidence=0.9)


def proposed(pet="Mochi", desc="Morning walk", start="08:00", dur=30, pri="medium", freq="once"):
    return ProposedTask(pet, Task(desc, start, dur, pri, freq))


def reply(*tasks):
    return {"refuse": False, "refuse_reason": "", "reasoning": "r", "summary": "s",
            "confidence": 0.9, "tasks": [
                {"pet_name": t.pet_name, "description": t.task.description,
                 "start_time": f"{t.task.start_time:%H:%M}", "duration_minutes": t.task.duration_minutes,
                 "priority": t.task.priority, "frequency": t.task.frequency} for t in tasks]}


# --- expect() --------------------------------------------------------------------------


def test_expect_passes_a_result_that_meets_everything():
    check = expect(status={"ok"}, max_calls=1, min_tasks=1, pets={"Mochi"}, house_rules=True,
                   no_conflicts=True, no_tasks_for="Rex")
    assert check(plan(tasks=[proposed()]), sample_owner()) == []


def test_expect_reports_each_missed_expectation():
    check = expect(status={"ok"}, max_calls=0, min_tasks=2, pets={"Luna"}, all_daily=True,
                   priority="high", problem="over_budget", no_tasks_for="Mochi")
    fails = check(plan(status="needs_review", calls=2, tasks=[proposed()]), sample_owner())
    assert len(fails) == 8
    assert "status was needs_review, expected ok" in fails
    assert "a task was created for 'Mochi'" in fails


def test_expect_rechecks_conflicts_with_the_scheduler():
    owner = sample_owner()
    owner.find_pet("Mochi").add_task(Task("Vet visit", "08:00", 60))
    fails = expect(no_conflicts=True)(plan(tasks=[proposed(start="08:30")]), owner)
    assert fails == ["the final plan still has a time conflict"]


def test_expect_reports_broken_house_rules():
    fails = expect(house_rules=True)(plan(tasks=[proposed(desc="Walk Mochi")]), sample_owner())
    assert any("No pet name" in f for f in fails)


def test_expect_checks_task_minutes_and_retrieved_notes():
    result = plan(tasks=[proposed(dur=30)])
    result.notes = ["Walks for adult dogs (dogs.md)"]
    fails = expect(max_minutes=20, note="Walks for senior dogs")(result, sample_owner())
    assert fails == ["a task is longer than 20 minutes",
                     "care note 'Walks for senior dogs' was not retrieved"]
    result.notes.append("Walks for senior dogs (dogs.md)")
    assert expect(note="Walks for senior dogs")(result, sample_owner()) == []


def test_expect_finds_reported_problem_kinds():
    result = plan(status="needs_review", problems=[Problem("over_budget", "too long")])
    assert expect(problem="over_budget")(result, sample_owner()) == []


# --- Runner and report ------------------------------------------------------------------


def test_run_case_repeats_with_a_fresh_owner_and_judges_consistency():
    case = EvalCase("walk", "Walk Mochi at 8", "ok", expect(status={"ok"}, min_tasks=1))
    fake = FakeLLM([reply(proposed())] * 3)
    outcome = run_case(case, fake, runs=3)
    assert outcome.passed and outcome.consistent and outcome.passed_runs == 3
    assert len(fake.calls) == 3


def test_inconsistent_runs_are_flagged():
    case = EvalCase("walk", "Walk Mochi at 8", "ok", expect(status={"ok"}))
    fake = FakeLLM([reply(proposed()), {"refuse": True, "refuse_reason": "no", "reasoning": "",
                                        "tasks": [], "summary": "", "confidence": 0}])
    outcome = run_case(case, fake, runs=2)
    assert not outcome.passed and not outcome.consistent and outcome.passed_runs == 1


def test_guard_cases_pass_without_any_model_call():
    guard_cases = [c for c in CASES if c.name in ("dose question", "empty input", "too long")]
    fake = FakeLLM([])
    for case in guard_cases:
        assert run_case(case, fake, runs=2).passed, case.name
    assert fake.calls == []


def test_case_setup_runs_on_each_fresh_owner():
    case = next(c for c in CASES if c.name == "clash with existing task")
    owner = case.make_owner()
    assert owner.find_pet("Mochi").tasks[0].description == "Vet visit"
    assert case.make_owner() is not owner


def test_cases_are_unique_and_documented():
    assert len({c.name for c in CASES}) == len(CASES) >= 10
    assert all(c.criteria and c.request is not None for c in CASES)


def test_write_report_has_a_table_row_per_case(tmp_path):
    cases = [EvalCase("walk", "Walk Mochi at 8", "ok", expect(status={"ok"})),
             EvalCase("blank", "  ", "refused", expect(status={"refused"}, max_calls=0))]
    fake = FakeLLM([reply(proposed())] * 2)
    results = [run_case(c, fake, runs=2) for c in cases]
    path = tmp_path / "eval.md"
    write_report(results, 2, "fake-llm", path)
    text = path.read_text(encoding="utf-8")
    assert "**Summary:** 2/2 cases passed (4/4 runs) · 2/2 consistent" in text
    assert '| 1 | "Walk Mochi at 8" | ok | ✅ Pass (2/2) |' in text
    assert "| 2 | (only spaces) | refused | ✅ Pass (2/2) |" in text
    assert "## Failures\n\nNone." in text
