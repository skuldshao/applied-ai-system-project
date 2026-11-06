"""End-to-end demo of the PawPal+ AI Planner in the terminal, using the real Claude API.

The scenario plans a day for Jordan, Mochi (dog) and Luna (cat). Each request goes through the
agent (guard → plan → validate → check → decide → fix); plans with status "ok" are approved,
standing in for the owner clicking Approve in the app, and plans that need review are left
out. The finished schedule is printed at the end.

    python demo.py                        # the full scenario; also saves logs/demo_output.txt
    python demo.py "Walk Mochi at 7am"    # plan one request of your own (nothing is saved)

Every run is added to logs/agent_trace.md.
"""

from __future__ import annotations

import re
import sys
import textwrap
from pathlib import Path
from typing import List, TextIO

from tabulate import tabulate

from ai_planner import PlanResult, apply_plan, plan_request, save_trace
from formatting import colorize, task_label
from llm_client import ClaudeClient, LLMError
from main import COLOR, TABLE_FORMAT, heading, print_schedule, priority_cell
from pawpal_logging import setup_logging
from pawpal_system import Owner, Scheduler
from sample_data import sample_owner

OUTPUT_FILE = Path(__file__).parent / "logs" / "demo_output.txt"

# (request, what it shows). Run in order, so later requests see the tasks approved earlier.
SCENARIO = [
    ("Feed Mochi at 7am and 6pm, and give him his heart pill with breakfast",
     "a normal request: meals and medication, planned with the house rules"),
    ("Luna needs her eye drops at 7am and 9pm, and brush her this evening",
     "a second pet, with a 7am request that collides with Mochi's breakfast"),
    ("Take Mochi for a 60 minute walk at 10am and play fetch with him for 45 minutes at 4pm",
     "more than the time left today, so the agent stops for the owner's decision"),
    ("How much Benadryl can I give Mochi?",
     "a medication-dose question, blocked by the input guard before any model call"),
    ("Write me a poem about cats",
     "an off-topic request, refused by the model itself"),
]

STATUS_TEXT = {"ok": "✅ ok", "needs_review": "⚠️ needs review", "refused": "🛡️ refused",
               "error": "❌ error"}
ANSI_CODE = re.compile(r"\x1b\[[0-9;]*m")


class Tee:
    """Write to the terminal (with colors) and keep a color-free copy for the log file."""

    def __init__(self, stream: TextIO) -> None:
        self.stream, self.parts = stream, []

    def write(self, text: str) -> int:
        self.parts.append(ANSI_CODE.sub("", text))
        return self.stream.write(text)

    def flush(self) -> None:
        self.stream.flush()

    def isatty(self) -> bool:
        return self.stream.isatty()

    def text(self) -> str:
        return "".join(self.parts)


def wrap(text: str, indent: int) -> str:
    """Wrap text to 100 columns; every line after the first starts `indent` columns in."""
    return textwrap.fill(text, width=100, initial_indent=" " * indent,
                         subsequent_indent=" " * indent).lstrip()


def print_result(result: PlanResult) -> None:
    """Print the agent's steps, the proposed tasks and its summary."""
    for step in result.trace:
        # 2 spaces + icon (2 columns) + space + 13-wide name + space = detail starts at column 19.
        print(f"  {step.icon} {step.name:<13} {wrap(step.detail, indent=19)}")
    if result.tasks:
        print(tabulate(
            [[p.task.time_window(), p.pet_name, task_label(p.task), p.task.duration_minutes,
              priority_cell(p.task.priority), p.task.frequency] for p in result.tasks],
            headers=["Time", "Pet", "Task", "Min", "Priority", "Repeats"],
            tablefmt=TABLE_FORMAT,
        ))
    if result.summary:
        print(f"  💬 {wrap(result.summary, indent=5)}")


def run_request(owner: Owner, client: ClaudeClient, request: str, approve: bool) -> PlanResult:
    """Plan one request, print it, save its trace, and approve it if it's ok and approve is set."""
    result = plan_request(owner, request, client)
    save_trace(result)
    print_result(result)
    if approve and result.status == "ok":
        print(f"  👤 Approved: {apply_plan(owner, result)} task(s) added to the schedule.")
    elif result.can_apply:
        print("  👤 Not approved: the owner reviews the problems above first.")
    return result


def run_scenario(client: ClaudeClient) -> None:
    owner = sample_owner(available_minutes=90)
    print(colorize("🐾 PawPal+ AI Planner demo", "bold", COLOR))
    print(f"Owner: {owner.name} · Pets: Mochi (dog, 3), Luna (cat, 5) · "
          f"{owner.available_minutes} minutes free today · model: {client.model}")
    results: List[PlanResult] = []
    for number, (request, shows) in enumerate(SCENARIO, start=1):
        heading(f"━━━ Request {number}/{len(SCENARIO)} ━━━ shows {shows}")
        print(f'  💬 "{request}"')
        results.append(run_request(owner, client, request, approve=True))

    print_schedule(owner, Scheduler(owner))
    heading("📋 Demo summary")
    print(tabulate(
        [[n, r.request[:52] + ("…" if len(r.request) > 52 else ""), STATUS_TEXT[r.status],
          r.llm_calls, r.fix_rounds, f"{r.confidence:.2f}" if r.can_apply else "—"]
         for n, r in enumerate(results, start=1)],
        headers=["#", "Request", "Result", "Calls", "Fixes", "Confidence"],
        tablefmt=TABLE_FORMAT,
    ))


def main() -> None:
    setup_logging()
    try:
        client = ClaudeClient()
    except LLMError as err:
        raise SystemExit(f"❌ {err}") from err

    if len(sys.argv) > 1:  # one request of your own
        request = " ".join(sys.argv[1:])
        print(f'💬 "{request}"  (sample owner: Mochi the dog and Luna the cat)')
        run_request(sample_owner(), client, request, approve=False)
        return

    tee = Tee(sys.stdout)
    sys.stdout = tee
    try:
        run_scenario(client)
    finally:
        sys.stdout = tee.stream
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(f"$ python demo.py\n{tee.text()}", encoding="utf-8")
    print(f"\n📄 Output saved to {OUTPUT_FILE.relative_to(Path(__file__).parent)}; "
          "traces added to logs/agent_trace.md")


if __name__ == "__main__":
    main()
