"""Terminal testing ground for PawPal+ logic. Run: python main.py"""

from datetime import time

from tabulate import tabulate

from formatting import (
    color_enabled,
    colorize,
    priority_badge,
    status_badge,
    task_label,
)
from pawpal_system import Owner, Pet, Scheduler, Task

# Rounded box-drawing borders. tabulate uses wcwidth to measure emojis as two columns wide
# and skips ANSI color codes when measuring, so colored, emoji-filled columns still line up.
TABLE_FORMAT = "rounded_outline"
# Decided once: color only when printing to a real terminal and NO_COLOR isn't set.
COLOR = color_enabled()


def heading(text: str) -> None:
    """Print a bold section heading with a blank line before it."""
    print()
    print(colorize(text, "bold", COLOR))


def priority_cell(priority: str) -> str:
    """Return the priority badge (e.g. "🔴 high") in its traffic-light terminal color."""
    return colorize(priority_badge(priority), priority, COLOR)


def budget_bar(used: int, available: int, width: int = 30) -> str:
    """Draw how much of the time budget is used, e.g. "███████░░░ 60/90 min (67%)"."""
    share = used / available if available else 0
    filled = round(share * width)
    return f"{'█' * filled}{'░' * (width - filled)} {used}/{available} min ({share:.0%})"


def print_tasks(title: str, tasks) -> None:
    """Print a titled table of (pet, task) pairs with due date, time, priority, and status.

    Finished tasks are dimmed so the eye goes to the ones still to do.
    """
    heading(title)
    if not tasks:
        print("  (none)")
        return
    rows = []
    for pet, task in tasks:
        row = [
            f"{task.due_date:%a %b %d}",
            task.start_time.strftime("%H:%M"),
            pet.name,
            task_label(task),
            priority_cell(task.priority),
            status_badge(task),
        ]
        if task.completed:
            row = [colorize(cell, "dim", COLOR) for cell in row]
        rows.append(row)
    print(tabulate(rows, headers=["Due", "Time", "Pet", "Task", "Priority", "Status"],
                   tablefmt=TABLE_FORMAT))


def print_schedule(owner: Owner, scheduler: Scheduler) -> None:
    """Print today's plan as a table, a time-budget bar, skipped tasks and conflict warnings."""
    schedule = scheduler.todays_schedule()
    used = sum(task.duration_minutes for _, task in schedule)
    # Tasks in any conflicting pair get a ⚡ in the table, next to the warnings below.
    clashing = {id(t) for pair in scheduler.find_conflicts() for _, t in pair}

    heading(f"🐾 Today's Schedule for {owner.name}")
    print(tabulate(
        [
            [
                task.time_window(),
                pet.name,
                task_label(task),
                task.duration_minutes,
                priority_cell(task.priority),
                "⚡" if id(task) in clashing else "",
            ]
            for pet, task in schedule
        ],
        headers=["Time", "Pet", "Task", "Min", "Priority", "Clash"],
        tablefmt=TABLE_FORMAT,
    ))
    print(f"Time budget  {budget_bar(used, owner.available_minutes)}")

    skipped = scheduler.skipped_tasks()
    if skipped:
        print("\nSkipped (not enough time):")
        for pet, task in skipped:
            print(f"  ❌ {pet.name}: {task_label(task)} ({task.duration_minutes} min, "
                  f"{priority_cell(task.priority)})")

    # Conflicts come back as warning strings, so printing them never stops the program.
    warnings = scheduler.conflict_warnings()
    print()
    if warnings:
        print(colorize(f"Conflicts ({len(warnings)}):", "high", COLOR))
        for warning in warnings:
            print(f"  {warning}")
    else:
        print(colorize("✅ No time conflicts.", "low", COLOR))


def print_priority_plan(title: str, owner: Owner, scheduler: Scheduler) -> None:
    """Print today's plan ordered by priority first, then time, with skipped tasks at the end."""
    plan = scheduler.todays_schedule(order="priority")
    used = sum(task.duration_minutes for _, task in plan)
    rows = [
        [rank, priority_cell(task.priority), task.start_time.strftime("%H:%M"), pet.name,
         task_label(task), task.duration_minutes, "✅ planned"]
        for rank, (pet, task) in enumerate(plan, start=1)
    ]
    # Skipped tasks have no rank (None, shown as "-" by missingval); listed last and dimmed.
    rows += [
        [colorize(cell, "dim", COLOR) if isinstance(cell, str) else cell for cell in [
            None, priority_badge(task.priority), task.start_time.strftime("%H:%M"), pet.name,
            task_label(task), task.duration_minutes, "❌ no time"]]
        for pet, task in scheduler.skipped_tasks()
    ]
    print(f"\n{title}  {budget_bar(used, owner.available_minutes)}")
    print(tabulate(rows, headers=["#", "Priority", "Time", "Pet", "Task", "Min", "Plan"],
                   tablefmt=TABLE_FORMAT, missingval="-"))


def print_free_slots(scheduler: Scheduler) -> None:
    """Print the next free slot for a few task lengths, as a table."""
    heading("🔎 Next free slots")
    rows = []
    for minutes, earliest in [(10, "07:00"), (45, "07:00"), (30, "18:00")]:
        slot = scheduler.find_next_available_slot(minutes, earliest=earliest)
        rows.append([f"{minutes} min", earliest, slot.strftime("%H:%M") if slot else "none today"])
    print(tabulate(rows, headers=["Length", "Not before", "Free at"], tablefmt=TABLE_FORMAT))


def main() -> None:
    """Build a sample owner with two pets, then demo each scheduling feature."""
    owner = Owner(name="Jordan", available_minutes=90)

    mochi = Pet(name="Mochi", species="dog", age=3)
    luna = Pet(name="Luna", species="cat", age=5)
    owner.add_pet(mochi)
    owner.add_pet(luna)

    # Added deliberately out of order; some times are "HH:MM" strings.
    mochi.add_task(Task("Dinner", "18:00", 10, "high", "daily"))
    mochi.add_task(Task("Fetch in the yard", "16:00", 40, "low", "once"))
    mochi.add_task(Task("Morning walk", time(7, 30), 30, "high", "daily"))
    luna.add_task(Task("Brush fur", "19:30", 15, "medium", "weekly"))
    luna.add_task(Task("Thyroid medication", "8:15", 5, "high", "daily"))
    luna.add_task(Task("Breakfast", time(8, 0), 5, "high", "daily"))
    # Deliberate conflicts: same time for different pets, and same time for the same pet.
    mochi.add_task(Task("Brush teeth", "08:15", 10, "medium", "daily"))  # = Luna's medication
    mochi.add_task(Task("Flea treatment", "07:30", 5, "high", "once"))  # = Mochi's walk

    scheduler = Scheduler(owner)
    # Completing recurring tasks adds their next occurrence automatically.
    scheduler.mark_task_complete("Luna", "Breakfast")  # daily  -> new copy due tomorrow
    scheduler.mark_task_complete("Luna", "Brush fur")  # weekly -> new copy due in 7 days
    scheduler.mark_task_complete("Mochi", "Fetch in the yard")  # once -> no new copy

    print_tasks("All tasks (insertion order)", scheduler.get_tasks())
    print_tasks("All tasks sorted by time", scheduler.sort_by_time(scheduler.get_tasks()))
    print_tasks("Mochi's tasks", scheduler.sort_by_time(scheduler.get_tasks(pet_name="Mochi")))
    print_tasks("Completed tasks", scheduler.get_tasks(completed=True))
    print_tasks(
        "Luna's pending tasks",
        scheduler.sort_by_time(scheduler.get_tasks(pet_name="luna", completed=False)),
    )

    print_schedule(owner, scheduler)

    # Priority-based scheduling: the same plan, most important first. Ties within a
    # priority are broken by due date, then start time, then pet name.
    heading("⭐ Priority-first view of today's plan")
    print_priority_plan("Budget 90 min", owner, scheduler)
    # With less time, priority decides what makes the cut: high tasks are taken first,
    # and lower ones are dropped once the budget runs out.
    owner.available_minutes = 50
    print_priority_plan("Budget 50 min", owner, scheduler)
    owner.available_minutes = 90

    # Next available slot: the earliest gap in today's plan that fits a task of this length.
    print_free_slots(scheduler)
    print()

if __name__ == "__main__":
    main()
