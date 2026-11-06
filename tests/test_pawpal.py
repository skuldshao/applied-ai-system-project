"""Tests for PawPal+ core classes. Run: python -m pytest"""

import json
from datetime import date, time, timedelta

import pytest

from pawpal_system import Owner, Pet, Scheduler, Task


def test_mark_complete_changes_status():
    """mark_complete() flips a new task from pending to completed."""
    task = Task("Morning walk", time(7, 30), 30, "high", "daily")
    assert task.completed is False

    task.mark_complete()

    assert task.completed is True


def test_add_task_increases_pet_task_count():
    """add_task() adds the task to the pet's task list."""
    pet = Pet(name="Mochi", species="dog", age=3)
    assert len(pet.tasks) == 0

    pet.add_task(Task("Dinner", time(18, 0), 10, "high", "daily"))

    assert len(pet.tasks) == 1


def make_scheduler() -> Scheduler:
    """Build a two-pet scheduler with four tasks, including two that start at 08:00."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi", species="dog")
    luna = Pet(name="Luna", species="cat")
    owner.add_pet(mochi)
    owner.add_pet(luna)
    mochi.add_task(Task("Dinner", "18:00", 10, "high"))
    mochi.add_task(Task("Morning walk", "7:30", 30, "high"))
    luna.add_task(Task("Brush fur", "08:00", 15, "low"))
    luna.add_task(Task("Breakfast", "08:00", 5, "high"))
    return Scheduler(owner)


def test_task_accepts_hh_mm_string():
    """Start times given as "H:MM" or "HH:MM" strings become time objects."""
    assert Task("Walk", "7:05").start_time == time(7, 5)
    assert Task("Walk", "19:45").start_time == time(19, 45)


@pytest.mark.parametrize("bad", ["25:00", "7.30", "noon", ""])
def test_task_rejects_bad_time_string(bad):
    """Invalid time strings raise ValueError when the task is created."""
    with pytest.raises(ValueError):
        Task("Walk", bad)


def test_sort_by_time_orders_chronologically_with_priority_tiebreak():
    """sort_by_time() orders by start time, putting the high-priority task first on a tie."""
    scheduler = make_scheduler()

    ordered = [t.description for _, t in scheduler.sort_by_time(scheduler.get_tasks())]

    assert ordered == ["Morning walk", "Breakfast", "Brush fur", "Dinner"]


def test_get_tasks_filters_by_pet_name_case_insensitively():
    """get_tasks(pet_name) matches pet names regardless of case and spaces."""
    scheduler = make_scheduler()

    tasks = scheduler.get_tasks(pet_name="luna")

    assert {t.description for _, t in tasks} == {"Brush fur", "Breakfast"}


def test_get_tasks_filters_by_status_and_pet_together():
    """The pet and completed filters can be combined in one get_tasks() call."""
    scheduler = make_scheduler()
    scheduler.mark_task_complete("Mochi", "Dinner")

    assert [t.description for _, t in scheduler.get_tasks(completed=True)] == ["Dinner"]
    assert [t.description for _, t in scheduler.get_tasks("Mochi", completed=False)] == ["Morning walk"]
    assert scheduler.get_tasks(pet_name="Nobody") == []


TODAY = date(2026, 10, 3)


@pytest.mark.parametrize(
    "frequency, expected_due",
    [("daily", date(2026, 10, 4)), ("weekly", date(2026, 10, 10))],
)
def test_next_occurrence_moves_due_date_forward(frequency, expected_due):
    """Daily tasks come back 1 day later and weekly tasks 7 days later."""
    task = Task("Walk", "07:30", 30, "high", frequency, due_date=TODAY)
    task.mark_complete()

    nxt = task.next_occurrence(today=TODAY)

    assert nxt.due_date == expected_due
    assert nxt.completed is False
    assert (nxt.description, nxt.start_time, nxt.priority) == ("Walk", time(7, 30), "high")


def test_next_occurrence_is_none_for_one_off_task():
    """A "once" task has no next occurrence."""
    assert Task("Vet visit", "10:00", frequency="once").next_occurrence() is None


def test_next_occurrence_handles_month_and_year_rollover():
    """Next due dates roll over month and year boundaries correctly."""
    assert Task("Feed", "8:00", frequency="daily", due_date=date(2026, 1, 31)).next_occurrence(
        today=date(2026, 1, 31)
    ).due_date == date(2026, 2, 1)
    assert Task("Feed", "8:00", frequency="weekly", due_date=date(2026, 12, 29)).next_occurrence(
        today=date(2026, 12, 29)
    ).due_date == date(2027, 1, 5)


def test_overdue_task_finished_late_is_next_due_tomorrow():
    """A daily task finished days late is next due tomorrow, not in the past."""
    task = Task("Feed", "8:00", frequency="daily", due_date=TODAY - timedelta(days=3))

    assert task.next_occurrence(today=TODAY).due_date == TODAY + timedelta(days=1)


def test_completing_daily_task_adds_tomorrows_copy():
    """Completing a daily task keeps it as history and adds a pending copy for tomorrow."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi", species="dog")
    owner.add_pet(mochi)
    mochi.add_task(Task("Walk", "07:30", 30, "high", "daily", due_date=TODAY))
    scheduler = Scheduler(owner)

    assert scheduler.mark_task_complete("Mochi", "Walk", today=TODAY) is True

    done, upcoming = mochi.tasks
    assert done.completed is True and done.due_date == TODAY
    assert upcoming.completed is False and upcoming.due_date == TODAY + timedelta(days=1)
    # Tomorrow's copy isn't on today's schedule, but shows up tomorrow.
    assert scheduler.todays_schedule(today=TODAY) == []
    assert scheduler.todays_schedule(today=TODAY + timedelta(days=1)) == [(mochi, upcoming)]


def test_completing_one_off_task_adds_nothing():
    """Completing a "once" task doesn't add a new copy."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi", species="dog")
    owner.add_pet(mochi)
    mochi.add_task(Task("Vet visit", "10:00", frequency="once", due_date=TODAY))

    Scheduler(owner).mark_task_complete("Mochi", "Vet visit", today=TODAY)

    assert len(mochi.tasks) == 1


def test_mark_complete_targets_pending_copy_each_time():
    """Completing the same task twice completes the new pending copy, not the old one."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi", species="dog")
    owner.add_pet(mochi)
    mochi.add_task(Task("Walk", "07:30", frequency="daily", due_date=TODAY))
    scheduler = Scheduler(owner)

    scheduler.mark_task_complete("Mochi", "Walk", today=TODAY)
    scheduler.mark_task_complete("Mochi", "Walk", today=TODAY)

    # Each call completes the current pending copy and adds the next one.
    assert [t.completed for t in mochi.tasks] == [True, True, False]
    assert [t.due_date.day for t in mochi.tasks] == [3, 4, 5]


def test_mark_complete_returns_false_when_missing():
    """mark_task_complete() returns False for an unknown pet or task instead of raising."""
    scheduler = make_scheduler()

    assert scheduler.mark_task_complete("Nobody", "Dinner") is False
    assert scheduler.mark_task_complete("Mochi", "Nap") is False


def conflict_scheduler(*tasks_by_pet):
    """Build a scheduler from (pet_name, Task) pairs, all due TODAY, with plenty of time."""
    # 600 minutes is enough that no task gets skipped, so every task is checked for conflicts.
    owner = Owner(name="Jordan", available_minutes=600)
    for pet_name, task in tasks_by_pet:
        # Reuse the pet if it already exists, so several tasks can belong to the same pet.
        pet = owner.find_pet(pet_name)
        if pet is None:
            pet = Pet(name=pet_name, species="dog")
            owner.add_pet(pet)
        # Pin the date so results don't depend on the day the tests are run.
        task.due_date = TODAY
        pet.add_task(task)
    return Scheduler(owner)


def conflict_names(scheduler):
    """Return the conflicting pairs as (description, description) tuples, which are easy to compare."""
    return [(a.description, b.description) for (_, a), (_, b) in scheduler.find_conflicts(TODAY)]


def test_same_time_different_pets_is_a_conflict():
    """Two pets' tasks at the same time are reported as a conflict."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Brush teeth", "08:15", 10)),  # 08:15-08:25
        ("Luna", Task("Medication", "08:15", 5)),  # 08:15-08:20, different pet, same start
    )

    # Same time and priority, so the tie-breaker orders pets by name: Luna before Mochi.
    assert conflict_names(scheduler) == [("Medication", "Brush teeth")]
    [warning] = scheduler.conflict_warnings(TODAY)
    assert "Luna & Mochi" in warning and "start at the same time" in warning


def test_same_time_same_pet_is_a_conflict():
    """Two tasks for the same pet at the same time are reported as a conflict."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Walk", "07:30", 30)),
        ("Mochi", Task("Flea treatment", "07:30", 5)),  # same pet, same start
    )

    # Unpacking into [warning] also checks there is exactly one warning.
    [warning] = scheduler.conflict_warnings(TODAY)
    assert "same pet: Mochi" in warning


def test_partial_overlap_is_a_conflict():
    """A task starting partway through another is reported as a conflict."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Walk", "07:30", 30)),  # 07:30-08:00
        ("Luna", Task("Breakfast", "07:45", 5)),  # starts mid-walk
    )

    assert conflict_names(scheduler) == [("Walk", "Breakfast")]
    # The warning shows each task's full time window, not just its start time.
    assert "07:30-08:00" in scheduler.conflict_warnings(TODAY)[0]


def test_back_to_back_tasks_do_not_conflict():
    """A task starting exactly when another ends is not a conflict."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Walk", "07:30", 30)),  # ends 08:00
        ("Luna", Task("Breakfast", "08:00", 5)),  # starts the minute the walk ends
    )

    # Touching windows aren't an overlap, so there are no pairs and no warnings.
    assert scheduler.find_conflicts(TODAY) == []
    assert scheduler.conflict_warnings(TODAY) == []


def test_long_task_conflicts_with_every_task_inside_it():
    """A long task is reported once for each shorter task that overlaps it."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Hike", "09:00", 120)),  # 09:00-11:00
        ("Luna", Task("Feed", "09:30", 5)),
        ("Luna", Task("Play", "10:30", 15)),
    )

    # Feed and Play don't overlap each other, but both overlap the hike.
    assert conflict_names(scheduler) == [("Hike", "Feed"), ("Hike", "Play")]


def test_completed_and_future_tasks_are_not_checked_for_conflicts():
    """Completed tasks and future recurring copies are left out of conflict checks."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Walk", "07:30", 30, frequency="daily")),
        ("Luna", Task("Breakfast", "07:30", 5)),
    )
    scheduler.mark_task_complete("Mochi", "Walk", today=TODAY)  # adds tomorrow's walk

    # Today's walk is done and tomorrow's isn't due yet, so Breakfast has nothing to clash with.
    assert scheduler.find_conflicts(TODAY) == []


# --- Sorting: priority order and edge cases -----------------------------------


def test_sort_by_priority_orders_high_to_low_then_by_time():
    """sort_by_priority() puts high before low and breaks ties by start time."""
    scheduler = make_scheduler()

    ordered = [t.description for _, t in scheduler.sort_by_priority(scheduler.get_tasks())]

    # The three high tasks come first, earliest start first; the low task comes last.
    assert ordered == ["Morning walk", "Breakfast", "Dinner", "Brush fur"]


def test_sorting_an_empty_list_returns_empty_list():
    """Both sort methods return an empty list for empty input."""
    assert Scheduler.sort_by_time([]) == []
    assert Scheduler.sort_by_priority([]) == []


def test_overdue_task_is_listed_before_todays_tasks():
    """sort_by_time() lists an overdue task before today's tasks, whatever its start time."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi", species="dog")
    owner.add_pet(mochi)
    mochi.add_task(Task("Walk", "07:00", due_date=TODAY))
    mochi.add_task(Task("Missed dinner", "18:00", due_date=TODAY - timedelta(days=1)))

    plan = [t.description for _, t in Scheduler(owner).todays_schedule(TODAY)]

    # due_date is the first sort key, so yesterday's task leads even though 18:00 > 07:00.
    assert plan == ["Missed dinner", "Walk"]


# --- Recurrence: finished early -------------------------------------------------


def test_weekly_task_finished_early_counts_from_its_due_date():
    """A weekly task finished early is next due a week after its original due date."""
    task = Task("Bath", "10:00", frequency="weekly", due_date=date(2026, 10, 10))

    # Done a week early: the next copy still lands a week after the original due date.
    assert task.next_occurrence(today=TODAY).due_date == date(2026, 10, 17)


# --- Daily plan: time budget ---------------------------------------------------


def budget_scheduler(available_minutes, *tasks):
    """Build a one-pet scheduler with the given time budget; every task is due TODAY."""
    owner = Owner(name="Jordan", available_minutes=available_minutes)
    mochi = Pet(name="Mochi", species="dog")
    owner.add_pet(mochi)
    for task in tasks:
        task.due_date = TODAY
        mochi.add_task(task)
    return Scheduler(owner)


def test_tasks_that_exactly_fill_the_budget_are_all_scheduled():
    """Tasks whose total equals available_minutes are all kept."""
    scheduler = budget_scheduler(
        45, Task("Walk", "07:00", 30, "high"), Task("Feed", "08:00", 15, "low")
    )

    # 30 + 15 == 45, and the check is <=, so nothing is skipped.
    assert len(scheduler.todays_schedule(TODAY)) == 2
    assert scheduler.skipped_tasks(TODAY) == []


def test_task_too_long_for_budget_is_skipped_but_shorter_one_still_fits():
    """A task that doesn't fit is skipped, but a shorter lower-priority one can still fit."""
    scheduler = budget_scheduler(
        40,
        Task("Walk", "07:00", 30, "high"),
        Task("Grooming", "09:00", 20, "medium"),  # 30 + 20 > 40, so skipped
        Task("Feed", "08:00", 10, "low"),  # 30 + 10 == 40, still fits
    )

    assert [t.description for _, t in scheduler.todays_schedule(TODAY)] == ["Walk", "Feed"]
    assert [t.description for _, t in scheduler.skipped_tasks(TODAY)] == ["Grooming"]


def test_zero_minutes_available_gives_empty_plan():
    """With no time available the plan is empty and every due task is skipped."""
    scheduler = budget_scheduler(0, Task("Walk", "07:00", 30))

    assert scheduler.todays_schedule(TODAY) == []
    assert len(scheduler.skipped_tasks(TODAY)) == 1


def test_due_tasks_includes_overdue_and_excludes_future_and_completed():
    """due_tasks() keeps overdue and today's tasks, and drops future and completed ones."""
    owner = Owner(name="Jordan")
    mochi = Pet(name="Mochi", species="dog")
    owner.add_pet(mochi)
    mochi.add_task(Task("Overdue", "07:00", due_date=TODAY - timedelta(days=2)))
    mochi.add_task(Task("Today", "08:00", due_date=TODAY))
    mochi.add_task(Task("Tomorrow", "09:00", due_date=TODAY + timedelta(days=1)))
    mochi.add_task(Task("Done", "10:00", completed=True, due_date=TODAY))

    due = {t.description for _, t in Scheduler(owner).due_tasks(TODAY)}

    assert due == {"Overdue", "Today"}


# --- Conflicts: more than two tasks and skipped tasks ---------------------------


def test_three_tasks_at_same_time_give_three_conflict_pairs():
    """Three tasks at the same time give all three conflicting pairs."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Walk", "08:00", 15)),
        ("Luna", Task("Feed", "08:00", 5)),
        ("Pip", Task("Meds", "08:00", 5)),
    )

    # Every pair clashes: A-B, A-C, B-C.
    assert len(scheduler.find_conflicts(TODAY)) == 3
    assert all("start at the same time" in w for w in scheduler.conflict_warnings(TODAY))


def test_task_skipped_for_time_is_not_reported_as_conflict():
    """A task left out of the plan for lack of time isn't reported as a conflict."""
    scheduler = budget_scheduler(
        30,
        Task("Walk", "08:00", 30, "high"),
        Task("Grooming", "08:00", 20, "low"),  # same start, but doesn't fit the budget
    )

    # Conflicts are checked on today's plan only, and Grooming never made the plan.
    assert scheduler.find_conflicts(TODAY) == []


# --- Empty data ----------------------------------------------------------------


@pytest.mark.parametrize("with_pet", [False, True])
def test_owner_with_no_pets_or_pet_with_no_tasks_returns_empty_results(with_pet):
    """Scheduler methods return empty results, not errors, when there is no data."""
    owner = Owner(name="Jordan")
    if with_pet:
        owner.add_pet(Pet(name="Mochi", species="dog"))
    scheduler = Scheduler(owner)

    assert scheduler.get_tasks() == []
    assert scheduler.due_tasks(TODAY) == []
    assert scheduler.todays_schedule(TODAY) == []
    assert scheduler.skipped_tasks(TODAY) == []
    assert scheduler.find_conflicts(TODAY) == []
    assert scheduler.conflict_warnings(TODAY) == []


# --- Validation ----------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [{"priority": "urgent"}, {"frequency": "monthly"}, {"duration_minutes": 0}, {"duration_minutes": -5}],
)
def test_task_rejects_invalid_fields(kwargs):
    """A bad priority, frequency, or duration raises ValueError."""
    with pytest.raises(ValueError):
        Task("Walk", "07:00", **kwargs)


def test_remove_task_removes_every_task_with_that_description():
    """remove_task() removes every task with that description, including history copies."""
    pet = Pet(name="Mochi", species="dog")
    pet.add_task(Task("Walk", "07:00", completed=True))
    pet.add_task(Task("Walk", "07:00"))
    pet.add_task(Task("Feed", "08:00"))

    assert pet.remove_task("Walk") is True
    # Completed history copies are removed too, not just the pending one.
    assert [t.description for t in pet.tasks] == ["Feed"]


# --- Regression tests for fixed bugs -------------------------------------------


def test_mark_task_complete_ignores_pet_name_case():
    """Regression: mark_task_complete() finds the pet whatever the name's case."""
    scheduler = make_scheduler()

    assert scheduler.mark_task_complete("mochi", "Dinner") is True


def test_task_running_past_midnight_conflicts_with_early_morning_task():
    """Regression: a task running past midnight conflicts with an early-morning task."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Night meds", "23:50", 20)),  # 23:50-00:10
        ("Luna", Task("Early feed", "00:05", 5)),
    )

    assert len(scheduler.find_conflicts(TODAY)) == 1


# --- Next available slot ---------------------------------------------------------


def test_empty_day_gives_earliest_allowed_time():
    """With nothing planned, the free slot is the earliest allowed time."""
    scheduler = conflict_scheduler()

    assert scheduler.find_next_available_slot(30, today=TODAY) == time(6, 0)
    assert scheduler.find_next_available_slot(30, earliest="09:15", today=TODAY) == time(9, 15)


def test_slot_skips_busy_time_and_allows_back_to_back():
    """The slot finder skips busy tasks and can start right when one ends."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Walk", "06:00", 30)),  # 06:00-06:30
        ("Luna", Task("Breakfast", "06:30", 10)),  # 06:30-06:40
    )

    # Starts exactly when Breakfast ends; touching end-to-start isn't a conflict.
    assert scheduler.find_next_available_slot(15, today=TODAY) == time(6, 40)


def test_slot_skips_a_gap_that_is_too_short():
    """A gap shorter than the task is skipped in favor of the next one that fits."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Walk", "07:00", 30)),  # 07:00-07:30
        ("Luna", Task("Meds", "07:40", 5)),  # 10-minute gap before this
        ("Luna", Task("Brush", "08:00", 15)),  # 15-minute gap before this
    )

    assert scheduler.find_next_available_slot(10, earliest="07:00", today=TODAY) == time(7, 30)
    assert scheduler.find_next_available_slot(15, earliest="07:00", today=TODAY) == time(7, 45)
    assert scheduler.find_next_available_slot(20, earliest="07:00", today=TODAY) == time(8, 15)


def test_slot_inside_a_long_task_is_not_offered():
    """No slot is offered inside a long task, even after a short task within it."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Hike", "07:00", 120)),  # 07:00-09:00
        ("Luna", Task("Meds", "07:30", 5)),  # inside the hike
    )

    assert scheduler.find_next_available_slot(10, earliest="07:00", today=TODAY) == time(9, 0)


def test_slot_returns_none_when_nothing_fits_before_latest():
    """The slot finder returns None when the task can't finish by latest."""
    scheduler = conflict_scheduler(("Mochi", Task("Walk", "21:00", 50)))  # 21:00-21:50

    assert scheduler.find_next_available_slot(15, earliest="21:00", today=TODAY) is None
    assert scheduler.find_next_available_slot(10, earliest="21:00", today=TODAY) == time(21, 50)


def test_slot_ignores_the_task_being_moved_and_unplanned_tasks():
    """Completed tasks and the ignore task don't block a slot."""
    walk = Task("Walk", "08:00", 30)
    done = Task("Old feed", "08:30", 30, completed=True)
    scheduler = conflict_scheduler(("Mochi", walk), ("Luna", done))

    assert scheduler.find_next_available_slot(30, earliest="08:00", today=TODAY) == time(8, 30)
    assert scheduler.find_next_available_slot(
        30, earliest="08:00", today=TODAY, ignore=walk) == time(8, 0)


def test_slot_respects_task_running_past_midnight():
    """A task running past midnight blocks the start of the morning."""
    scheduler = conflict_scheduler(("Mochi", Task("Night meds", "23:50", 20)))  # to 00:10

    assert scheduler.find_next_available_slot(5, earliest="00:00", today=TODAY) == time(0, 10)


def test_slot_found_by_finder_never_creates_a_conflict():
    """Placing a task at the returned slot creates no conflicts."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Walk", "07:00", 30)),
        ("Luna", Task("Meds", "07:35", 5)),
        ("Luna", Task("Brush", "07:50", 20)),
    )
    slot = scheduler.find_next_available_slot(15, earliest="07:00", today=TODAY)

    scheduler.owner.find_pet("Mochi").add_task(Task("Play", slot, 15, due_date=TODAY))

    assert scheduler.find_conflicts(TODAY) == []


def test_slot_rejects_non_positive_duration():
    """A zero-minute duration raises ValueError."""
    with pytest.raises(ValueError):
        conflict_scheduler().find_next_available_slot(0, today=TODAY)


# --- Persistence: save_to_json / load_from_json ---------------------------------


def test_save_and_load_round_trip_keeps_everything(tmp_path):
    """Saving and loading gives back an owner equal to the original, field by field."""
    scheduler = make_scheduler()
    scheduler.owner.available_minutes = 75
    scheduler.mark_task_complete("Mochi", "Dinner", today=TODAY)  # adds tomorrow's copy
    path = tmp_path / "data.json"

    scheduler.owner.save_to_json(path)
    loaded = Owner.load_from_json(path)

    # Dataclasses compare field by field, so this checks every pet and task value,
    # including time objects, due dates and completed flags.
    assert loaded == scheduler.owner
    assert loaded is not scheduler.owner


def test_loaded_owner_gives_the_same_schedule(tmp_path):
    """A reloaded owner produces the same plan and the same conflicts."""
    scheduler = make_scheduler()
    path = tmp_path / "data.json"
    scheduler.owner.save_to_json(path)

    reloaded = Scheduler(Owner.load_from_json(path))

    def plan(s):
        """Return the plan as (pet name, description) pairs for easy comparison."""
        return [(p.name, t.description) for p, t in s.todays_schedule()]

    assert plan(reloaded) == plan(scheduler)
    assert len(reloaded.find_conflicts()) == len(scheduler.find_conflicts())


def test_saved_file_is_readable_json(tmp_path):
    """The file stores times as "HH:MM" and dates as ISO strings, with no temp file left over."""
    owner = Owner(name="Jordan")
    pet = Pet(name="Mochi", species="dog")
    owner.add_pet(pet)
    pet.add_task(Task("Walk", "7:30", due_date=date(2026, 1, 31)))
    path = tmp_path / "data.json"

    owner.save_to_json(path)
    task = json.loads(path.read_text())["pets"][0]["tasks"][0]

    assert task["start_time"] == "07:30"
    assert task["due_date"] == "2026-01-31"
    assert not (tmp_path / "data.json.tmp").exists()


def test_save_overwrites_previous_data(tmp_path):
    """Saving again replaces the old file contents."""
    path = tmp_path / "data.json"
    owner = Owner(name="Jordan")
    owner.add_pet(Pet(name="Mochi", species="dog"))
    owner.save_to_json(path)

    owner.remove_pet("Mochi")
    owner.save_to_json(path)

    assert Owner.load_from_json(path).pets == []


def test_load_missing_file_returns_none(tmp_path):
    """Loading a file that doesn't exist returns None."""
    assert Owner.load_from_json(tmp_path / "nope.json") is None


@pytest.mark.parametrize(
    "content",
    [
        "{not json",
        '{"name": "Jordan"}',  # missing fields
        '{"name": "J", "available_minutes": 60, "pets": [{"name": "M", "species": "dog",'
        ' "age": 1, "tasks": [{"description": "Walk", "start_time": "25:00",'
        ' "duration_minutes": 10, "priority": "high", "frequency": "once",'
        ' "completed": false, "due_date": "2026-01-01"}]}]}',  # bad time
    ],
)
def test_load_bad_file_raises_value_error(tmp_path, content):
    """Broken JSON, missing fields, and bad values all raise ValueError."""
    path = tmp_path / "data.json"
    path.write_text(content)

    with pytest.raises(ValueError):
        Owner.load_from_json(path)


# --- Priority-based scheduling --------------------------------------------------


@pytest.mark.parametrize("given", ["High", "HIGH", " high "])
def test_priority_is_case_insensitive(given):
    """Priority is accepted in any case and stored lowercase."""
    assert Task("Walk", "07:00", priority=given).priority == "high"


def test_sort_by_priority_breaks_ties_by_date_then_time_then_pet():
    """Within a priority, sort_by_priority() orders by due date, then time, then pet name."""
    yesterday = TODAY - timedelta(days=1)
    scheduler = conflict_scheduler(
        ("Mochi", Task("Low early", "06:00", priority="low")),
        ("Mochi", Task("High late", "20:00", priority="high")),
        ("Mochi", Task("High at 8 (Mochi)", "08:00", priority="high")),
        ("Luna", Task("High at 8 (Luna)", "08:00", priority="high")),
        ("Luna", Task("Medium", "07:00", priority="medium")),
    )
    overdue = Task("High overdue", "21:00", priority="high", due_date=yesterday)
    scheduler.owner.find_pet("Luna").add_task(overdue)

    ordered = [t.description for _, t in scheduler.sort_by_priority(scheduler.get_tasks())]

    assert ordered == [
        "High overdue",  # same priority: an earlier due date wins, even at a later time
        "High at 8 (Luna)",  # same time: pet name breaks the tie
        "High at 8 (Mochi)",
        "High late",
        "Medium",
        "Low early",  # earliest time of all, but lowest priority
    ]


def test_todays_schedule_can_be_ordered_by_priority():
    """todays_schedule() lists the plan by time or by priority, as requested."""
    scheduler = conflict_scheduler(
        ("Mochi", Task("Play", "07:00", priority="low")),
        ("Mochi", Task("Walk", "09:00", priority="high")),
        ("Luna", Task("Brush", "08:00", priority="medium")),
    )

    def names(order):
        """Return the plan's task descriptions in the given order."""
        return [t.description for _, t in scheduler.todays_schedule(TODAY, order=order)]

    assert names("time") == ["Play", "Brush", "Walk"]
    assert names("priority") == ["Walk", "Brush", "Play"]


def test_priority_order_shows_the_same_tasks_as_time_order():
    """Both orders contain the same tasks; order changes only how the plan is listed."""
    scheduler = budget_scheduler(
        30,
        Task("Walk", "09:00", 20, "high"),
        Task("Brush", "08:00", 10, "medium"),
        Task("Play", "07:00", 15, "low"),  # doesn't fit
    )
    by_time = scheduler.todays_schedule(TODAY, order="time")
    by_priority = scheduler.todays_schedule(TODAY, order="priority")

    assert {id(t) for _, t in by_time} == {id(t) for _, t in by_priority}
    assert [t.description for _, t in by_priority] == ["Walk", "Brush"]


def test_todays_schedule_rejects_unknown_order():
    """An unknown order value raises ValueError."""
    with pytest.raises(ValueError):
        conflict_scheduler().todays_schedule(TODAY, order="alphabetical")
