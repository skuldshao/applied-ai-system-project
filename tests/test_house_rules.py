"""Tests for the house rules, the scorer, and the specialized prompt built from them."""

import json

import pytest

from ai_planner import plan_request
from house_rules import (
    DAILY,
    DURATION,
    NO_PET_NAME,
    PRIORITY,
    UNIQUE_NAME,
    check_house_rules,
    classify,
    rules_text,
    summarize,
)
from llm_client import FakeLLM
from pawpal_system import Task
from prompts import (
    BASELINE_SYSTEM_PROMPT,
    FEW_SHOT_EXAMPLES,
    PLAN_SCHEMA,
    SPECIALIZED_SYSTEM_PROMPT,
    get_system_prompt,
)
from sample_data import sample_owner


def broken(checks):
    return sorted({c.rule for c in checks if not c.passed})


# --- classify ------------------------------------------------------------------------


@pytest.mark.parametrize("name, category", [
    ("Breakfast", "meal"), ("Allergy pill with breakfast", "medication"), ("Eye drops", "medication"),
    ("Morning walk", "walk"), ("Trim nails", "grooming"), ("Play fetch", "play"),
    ("Litter box", "cleaning"), ("Vet checkup", "vet visit"),
])
def test_classify_finds_the_care_category(name, category):
    assert classify(name).category == category


def test_classify_returns_none_for_unknown_tasks():
    assert classify("Cuddle time") is None


# --- check_house_rules ---------------------------------------------------------------


def test_a_plan_that_follows_every_rule_passes():
    plan = [("Mochi", Task("Breakfast", "08:00", 10, "high", "daily")),
            ("Mochi", Task("Dinner", "18:00", 10, "high", "daily")),
            ("Mochi", Task("Morning walk", "07:00", 30, "medium", "once"))]
    checks = check_house_rules(plan)
    assert broken(checks) == []
    assert summarize(checks)[DAILY] == (2, 2)


def test_typical_baseline_mistakes_are_all_caught():
    # What the baseline prompt produced live: pet name in both names, 5-min meals, once.
    plan = [("Luna", Task("Feed Luna", "07:30", 5, "medium", "once")),
            ("Luna", Task("Feed Luna", "18:00", 5, "medium", "once"))]
    assert broken(check_house_rules(plan)) == sorted([NO_PET_NAME, UNIQUE_NAME, PRIORITY, DURATION, DAILY])


def test_pet_name_rule_matches_whole_words_only():
    plan = [("Lu", Task("Lunch", "12:00", 10, "high", "daily"))]
    assert NO_PET_NAME not in broken(check_house_rules(plan))


def test_durations_can_be_skipped_when_the_owner_gave_them():
    plan = [("Mochi", Task("Morning walk", "07:00", 45, "medium", "once"))]
    assert DURATION in broken(check_house_rules(plan))
    assert broken(check_house_rules(plan, check_durations=False)) == []


def test_unknown_tasks_are_only_checked_for_naming():
    checks = check_house_rules([("Mochi", Task("Cuddle time", "20:00", 7, "low", "once"))])
    assert {c.rule for c in checks} == {NO_PET_NAME, UNIQUE_NAME}


def test_summarize_counts_passes_per_rule_and_skips_unused_rules():
    plan = [("Mochi", Task("Mochi walk", "07:00", 30, "medium", "once"))]
    summary = summarize(check_house_rules(plan))
    assert summary[NO_PET_NAME] == (0, 1) and summary[PRIORITY] == (1, 1)
    assert DAILY not in summary


# --- The specialized prompt ------------------------------------------------------------


def test_every_few_shot_example_follows_the_house_rules():
    # Guards against the examples drifting away from the rules table.
    for example in FEW_SHOT_EXAMPLES:
        tasks = example["reply"]["tasks"]
        plan = [(t["pet_name"], Task(t["description"], t["start_time"], t["duration_minutes"],
                                     t["priority"], t["frequency"])) for t in tasks]
        assert broken(check_house_rules(plan)) == [], example["request"]


def test_few_shot_replies_match_the_schema_fields():
    for example in FEW_SHOT_EXAMPLES:
        reply = example["reply"]
        assert set(reply) == set(PLAN_SCHEMA["properties"])
        for t in reply["tasks"]:
            assert set(t) == set(PLAN_SCHEMA["properties"]["tasks"]["items"]["properties"])


def test_specialized_prompt_extends_the_baseline_with_rules_and_examples():
    assert SPECIALIZED_SYSTEM_PROMPT.startswith(BASELINE_SYSTEM_PROMPT)
    assert rules_text() in SPECIALIZED_SYSTEM_PROMPT
    assert json.dumps(FEW_SHOT_EXAMPLES[0]["reply"]) in SPECIALIZED_SYSTEM_PROMPT
    assert "house rules" not in BASELINE_SYSTEM_PROMPT
    assert get_system_prompt(True) is SPECIALIZED_SYSTEM_PROMPT
    assert get_system_prompt(False) is BASELINE_SYSTEM_PROMPT


def test_rules_text_lists_every_category():
    text = rules_text()
    for category in ("medication", "meal", "walk", "grooming", "play", "cleaning", "vet visit"):
        assert category in text


@pytest.mark.parametrize("specialized, expected_prompt, mode", [
    (True, SPECIALIZED_SYSTEM_PROMPT, "specialized"),
    (False, BASELINE_SYSTEM_PROMPT, "baseline"),
])
def test_planner_sends_the_chosen_prompt(specialized, expected_prompt, mode):
    reply = {"refuse": False, "refuse_reason": "", "reasoning": "r", "summary": "s",
             "confidence": 0.9, "tasks": [{"pet_name": "Mochi", "description": "Morning walk",
                                           "start_time": "08:00", "duration_minutes": 30,
                                           "priority": "medium", "frequency": "once"}]}
    fake = FakeLLM([reply])
    result = plan_request(sample_owner(), "Walk Mochi", fake, specialized=specialized)
    assert fake.calls[0]["system"] is expected_prompt
    assert result.prompt_mode == mode
