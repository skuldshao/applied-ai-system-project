"""Display helpers for PawPal+: task-type emojis, priority and status badges, and colors.

Shared by main.py (terminal) and app.py (Streamlit), so both show tasks the same way.
Nothing here changes any data; every function only turns a value into text.
"""

from __future__ import annotations

import os
import sys
from datetime import date
from typing import Optional, TextIO

from pawpal_system import Task

# Keyword -> emoji, checked in order, so put more specific words first
# ("teeth" before "brush", so "Brush teeth" gets 🦷 and "Brush fur" gets 🧼).
# Every emoji is a single character that terminals draw two columns wide, so tables line up.
TASK_EMOJIS = [
    (("med", "pill", "flea", "treatment", "vaccine"), "💊"),
    (("teeth", "dental"), "🦷"),
    (("walk", "jog", "hike"), "🦮"),
    (("breakfast", "dinner", "lunch", "feed", "food", "meal", "treat"), "🍖"),
    (("brush", "groom", "bath", "fur", "nail"), "🧼"),
    (("play", "fetch", "toy", "train"), "🎾"),
    (("vet", "checkup", "check-up"), "🩺"),
    (("litter", "clean", "cage", "tank"), "🧹"),
]
DEFAULT_EMOJI = "🐾"

# Traffic-light colors: red needs attention first, green can wait.
PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}

STATUS_BADGE = {
    "done": "✅ done",
    "overdue": "❗ overdue",
    "pending": "⏳ due today",
    "upcoming": "📅 upcoming",
}

# ANSI escape codes. A terminal reads them as "switch color"; they take up no space.
RESET = "\033[0m"
ANSI = {
    "high": "\033[1;31m",  # bold red
    "medium": "\033[33m",  # yellow
    "low": "\033[32m",  # green
    "dim": "\033[2m",  # faint, for finished tasks
    "bold": "\033[1m",
}


def task_emoji(description: str) -> str:
    """Pick an emoji for a task from words in its description.

    Matching ignores case. The first keyword group that matches wins; a task that matches
    nothing gets the paw print 🐾.

    Examples:
        "Morning walk" -> 🦮, "Thyroid medication" -> 💊, "Nap" -> 🐾
    """
    text = description.lower()
    for keywords, emoji in TASK_EMOJIS:
        if any(word in text for word in keywords):
            return emoji
    return DEFAULT_EMOJI


def task_label(task: Task) -> str:
    """Return the task's description with its type emoji in front, e.g. "🦮 Morning walk"."""
    return f"{task_emoji(task.description)} {task.description}"


def priority_badge(priority: str) -> str:
    """Return a colored-dot badge for a priority, e.g. "🔴 high"."""
    return f"{PRIORITY_EMOJI[priority]} {priority}"


def task_status(task: Task, today: Optional[date] = None) -> str:
    """Classify a task as "done", "overdue", "pending" (due today) or "upcoming".

    Args:
        task: The task to check.
        today: The date to compare against. Defaults to date.today(); tests pass a fixed date.
    """
    today = today or date.today()
    if task.completed:
        return "done"
    if task.due_date < today:
        return "overdue"
    if task.due_date == today:
        return "pending"
    return "upcoming"


def status_badge(task: Task, today: Optional[date] = None) -> str:
    """Return an emoji badge for the task's status, e.g. "✅ done" or "❗ overdue"."""
    return STATUS_BADGE[task_status(task, today)]


def color_enabled(stream: TextIO = sys.stdout) -> bool:
    """Return True if colored output should be used on this stream.

    Colors are off when the NO_COLOR environment variable is set (see no-color.org) or
    when output isn't a terminal, e.g. redirected to a file, so saved output stays clean.
    """
    return "NO_COLOR" not in os.environ and hasattr(stream, "isatty") and stream.isatty()


def colorize(text: str, style: str, enabled: bool = True) -> str:
    """Wrap text in the ANSI color for a style ("high", "medium", "low", "dim", "bold").

    Returns the text unchanged when enabled is False, so callers can pass color_enabled().
    """
    if not enabled:
        return text
    return f"{ANSI[style]}{text}{RESET}"
