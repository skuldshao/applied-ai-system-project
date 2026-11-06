"""Offline tests for the behaviour checks in compare_rag.py, so the RAG numbers can be trusted."""

import pytest

from ai_planner import PlanResult, ProposedTask
from compare_rag import (
    CASES,
    insulin_follows_meals,
    litter_is_daily,
    no_midday_walks,
    senior_walks_are_short,
    walk_waits_after_meal,
)
from pawpal_system import Task


def plan(*tasks):
    """A PlanResult holding (pet, description, start, minutes, frequency) tasks."""
    return PlanResult(request="r", status="ok", tasks=[
        ProposedTask(pet, Task(desc, start, minutes, "medium", freq))
        for pet, desc, start, minutes, freq in tasks])


def case(name_part):
    return next(c for c in CASES if name_part in c.request)


@pytest.mark.parametrize("minutes, expected", [(20, True), (15, True), (30, False)])
def test_senior_walks_are_short(minutes, expected):
    result = plan(("Rocky", "Morning walk", "08:00", minutes, "daily"),
                  ("Rocky", "Evening walk", "18:00", 20, "daily"))
    assert senior_walks_are_short(result, case("Rocky").make_owner()) is expected


@pytest.mark.parametrize("walk_start, expected", [("08:10", True), ("07:10", False), ("06:00", True)])
def test_walk_waits_after_meal(walk_start, expected):
    # Breakfast 07:00-07:10; a walk before breakfast is fine, one right after it is not.
    result = plan(("Mochi", "Breakfast", "07:00", 10, "daily"),
                  ("Mochi", "Morning walk", walk_start, 30, "once"))
    assert walk_waits_after_meal(result, case("after breakfast").make_owner()) is expected


@pytest.mark.parametrize("starts, expected", [
    (("08:10", "18:10"), True), (("08:20", "18:10"), True), (("08:00", "20:00"), False)])
def test_insulin_follows_meals(starts, expected):
    # Luna's meals come from the case setup: 08:00-08:10 and 18:00-18:10.
    result = plan(*[("Luna", f"Insulin {n}", s, 5, "daily") for n, s in enumerate(starts)])
    assert insulin_follows_meals(result, case("insulin").make_owner()) is expected


@pytest.mark.parametrize("start, expected", [("16:00", True), ("11:30", True), ("14:00", False)])
def test_no_midday_walks(start, expected):
    result = plan(("Mochi", "Afternoon walk", start, 30, "once"))
    assert no_midday_walks(result, case("afternoon").make_owner()) is expected


@pytest.mark.parametrize("freq, expected", [("daily", True), ("once", False)])
def test_litter_is_daily(freq, expected):
    result = plan(("Luna", "Litter box", "20:00", 10, freq))
    assert litter_is_daily(result, case("litter").make_owner()) is expected


def test_a_plan_without_the_task_never_passes():
    empty = plan()
    for c in CASES:
        assert c.check(empty, c.make_owner()) is False, c.request


def test_every_case_owner_has_rocky_and_the_insulin_case_has_luna_meals():
    for c in CASES:
        assert c.make_owner().find_pet("Rocky").age == 12
    luna = case("insulin").make_owner().find_pet("Luna")
    assert [t.description for t in luna.tasks] == ["Breakfast", "Dinner"]
