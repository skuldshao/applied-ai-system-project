# AI Interactions Log

> **Stretch features only.** Only fill in the sections that apply to stretch features you attempted. If you did not attempt a stretch feature, leave its section blank or delete it. This file is not required for the core project.

---

## Agent Workflow (SF7)

> Document your experience using an AI agent (e.g., Cursor Agent, Claude, Copilot) to make multi-step changes autonomously.

**Agent used:** Claude Code (Claude Opus) in VS Code, in auto mode.

**What task did you give the agent?**

I gave it the Challenge 1 prompt: add a third algorithmic capability that goes beyond the basic requirements (for example "next available slot" or weighted prioritization), and document the workflow here. I let it pick which capability to build.

It picked **next available slot** because it builds on the conflict detection I already had. The app's old conflict tip ("start the later task when the earlier one ends") could suggest a time that clashed with a third task, and a slot finder fixes that.

**What did the agent do?**

1. **Read the project first:** `pawpal_system.py`, `app.py`, `main.py`, the test helpers in `tests/test_pawpal.py`, the README and this file, so the new code would match the existing style (docstrings with Args/Returns, `(pet, task)` pairs, a `today` parameter for testing).
2. **`pawpal_system.py`:** added `Scheduler.find_next_available_slot(duration_minutes, earliest="06:00", latest="22:00", today=None, ignore=None)`. It collects the busy windows from `todays_schedule()`, sorts them, and sweeps once, moving the candidate start past each window it would overlap until a gap is long enough. It returns a `time`, or `None` if nothing fits before `latest`. It handles tasks that run past midnight (they also block the early morning) and allows back-to-back tasks, the same rules `find_conflicts()` uses.
3. **`tests/test_pawpal.py`:** added 9 tests: empty day, skipping busy time and back-to-back slots, skipping a gap that's too short, nothing offered inside a long task, `None` when nothing fits, ignoring completed tasks and the `ignore` task, the past-midnight case, "a task placed at the returned slot causes no conflict", and rejecting a zero duration. Ran `python -m pytest`: **53 passed**.
4. **`app.py`:** changed the 💡 tip under each conflict to call `find_next_available_slot()`, searching from when the earlier task ends and ignoring the task being moved. Added a **🔎 Find a free slot** expander under today's schedule (task length, "not before", "finish by").
5. **`main.py`:** added a "Next free slots" printout at the end of the demo, then ran `python main.py` to check the output.
6. **Checked the app headlessly** with Streamlit's `AppTest`: added a pet and three overlapping tasks (Walk 08:00, Meds 08:15, Feed 08:30, 20 minutes each) and confirmed there were no exceptions and the tips appeared. This showed the improvement: the old tip would have moved Meds to 08:20, right into Feed; the new one suggests **08:50**.
7. **`README.md`:** added a Features bullet, a row in the Smarter Scheduling table, a new section "5. Next available slot" with a worked example, a test-coverage group, updated test counts and pytest output, and the new `main.py` output.

**Corrections the agent made to its own work**

- It first used a placeholder variable name in one test (`conflict_pet`) and simplified it after the tests passed.
- It noticed that after its change, the README's "Sample Output" said it showed "the end" of `main.py`, which was no longer true, so it added the new slot lines there too.
- It guarded one edge case in the UI from the start: if the earlier task in a conflict ends past midnight, there's no time left today, so the app shows "No free slot left today" instead of trying to build an invalid `time`.

**What did you have to verify or fix manually?**

<!-- TODO (me): fill in after reviewing. Things I should check myself:
     - Run `streamlit run app.py` and try the conflict tips and the Find a free slot box.
     - Decide whether the 06:00-22:00 default window makes sense for a pet owner.
     - Note anything I changed by hand in the agent's code or wording. -->

**Design limits I accepted**

- It only finds a slot; it doesn't move tasks. The owner still decides.
- It looks at today's plan only, so tasks skipped for lack of time don't block a slot. That matches `find_conflicts()`, but it means a skipped task could later clash if the owner raises their available minutes.
- It doesn't check the owner's time budget. A free slot on the clock doesn't guarantee the new task fits in `available_minutes`.

---

## Prompt Comparison (SF11)

> Compare two different prompts (or two different models) on the same task.

**Shared prompt/task:** Design `next_weekly_due_date(due_date: date, completed_on:
date) -> date` for PawPal+. If a weekly task is completed early or on time,
schedule the next copy seven days after its original due date. If it is completed
late, schedule the next copy seven days after the completion date so it is not
immediately overdue. Use `datetime.date`, handle calendar rollovers, do not create
catch-up occurrences, explain the complexity, and propose edge-case tests.

| | Option A | Option B |
|-|----------|----------|
| **Model / tool used** | Claude Sonnet 5 through a Copilot coding agent | Gemini 3.8 Flash through a Copilot coding agent |
| **Prompt** | The shared weekly-task rescheduling prompt above, unchanged. | The same shared weekly-task rescheduling prompt, unchanged. |
| **Response summary** | Compared the two dates, chose the later one as the anchor, and added `timedelta(days=7)`. It supplied a Python function, complexity analysis, calendar-rollover explanation, and 11 tests. | Used the same anchor-date algorithm and supplied a Python function, complexity analysis, a categorized edge-case list, and 9 tests. |
| **What was useful** | It explained why `date + timedelta` safely crosses month, leap-year, and year boundaries. Its tests included a useful invariant: the result must always be exactly seven days after `max(due_date, completed_on)`. It also checked that the return value is a `date`, not a `datetime`. | Its answer was concise and organized. The early, on-time, slightly late, very late, leap-year, non-leap-year, month-end, and year-end examples made the behavior easy to verify. It clearly stated that a very late completion creates only one future occurrence rather than a backlog. |
| **Problems noticed** | It was more verbose than needed, repeated the same algorithm in two equivalent implementations, and called it a “single-expression form” even though its main function used a conditional assignment. These were presentation issues rather than correctness problems. | It did not include a general invariant test or verify the exact return type. Its explanation of Python date arithmetic was also less precise, so the tests carried more of the justification. These omissions did not make the algorithm incorrect. |
| **Decision** | **Selected as the primary explanation** because the invariant test gives the strongest reusable verification and the calendar reasoning is precise. | **Kept as supporting evidence** because its focused examples make the rule easy to understand, but it did not add a stronger algorithm than Option A. |

### Why this task is algorithmically interesting

Weekly recurrence sounds like simply adding seven days, but the date from which
those seven days are counted matters. Counting from the completion date every
time would gradually move the schedule when an owner completes a task early.
Counting from the old due date every time would create a new task that could
already be overdue when the owner finishes a very late task.

For example, suppose grooming is due on October 10:

- If the owner finishes it early on October 8, the next due date should remain
  October 17. Scheduling it for October 15 would move the normal grooming day
  two days earlier.
- If the owner finishes it on time on October 10, the next date is October 17.
- If the owner finishes it late on October 13, the next date should be October
  20. Scheduling it for October 17 would give the owner only four days before
  the task is due again.
- If the owner finishes it several weeks late, the system should still create
  only one new task. It should not fill the task list with missed weekly copies.

The rule can therefore be described in two steps:

1. Choose the later of the original due date and the actual completion date.
   This date becomes the anchor.
2. Add seven days to that anchor.

In Python, the complete calculation is:

```python
next_due_date = max(due_date, completed_on) + timedelta(days=7)
```

This operation has constant time and space complexity, or `O(1)`, because it
always performs one date comparison and one date addition regardless of how
early or late the task was completed.

### Detailed evaluation of Option A: Claude Sonnet 5

Claude first wrote the rule as two branches: use the original due date when the
task is early or on time, and use the completion date when it is late. It then
recognized that both branches can be represented by choosing the maximum of the
two dates. This directly matched the intended behavior.

The strongest part of Claude's response was its explanation of date arithmetic.
It explained that `datetime.date` and `timedelta` work in whole calendar days,
so Python handles month lengths, leap years, and year changes. This is safer
than manually checking whether a month has 28, 29, 30, or 31 days. Claude also
proposed tests for early, on-time, one-day-late, and very-late completion, plus
month-end, February, leap-day, and year-end transitions.

Its most useful test was an invariant:

```python
result - max(due_date, completed_on) == timedelta(days=7)
```

This checks the general rule rather than checking only individual examples.
Claude also tested that the result was a `date` instead of a `datetime`, which
supports the prompt's type requirement.

The main weakness was unnecessary repetition. Claude showed both a conditional
version and a compact version even though they produce identical results. It
also described the solution as a single expression but used a separate
conditional assignment in its main example. This did not affect correctness,
but it made the answer longer and slightly less consistent than necessary.

### Detailed evaluation of Option B: Gemini 3.8 Flash

Gemini reached the same rule independently. It called the chosen date the
"anchor date" and clearly explained that an early or on-time task stays anchored
to its original due date, while a late task resets its cadence from the
completion date.

Gemini's strongest feature was organization. Its examples covered the important
user situations without much extra explanation. It included tests for an early
completion, exact-date completion, a task two days late, a task three weeks
late, month rollover, leap and non-leap February, and year rollover. The test
for a task completed three weeks late was especially useful because it showed
that the algorithm creates one future occurrence and no catch-up backlog.

Gemini's answer was correct, but its verification was less general. It relied
only on example-based tests and did not state an invariant that covers every
valid pair of dates. It also did not test that the function returns a
`datetime.date` rather than a timestamp. Finally, it said Python handles
calendar boundaries but did not explain why as precisely as Claude did.

### Direct comparison

Both models produced the correct algorithm, so the decision was not based on
different output dates. Instead, I compared how well each response justified
and verified the solution:

- **Correctness:** Both followed all three recurrence cases correctly.
- **Clarity:** Gemini was shorter and easier to scan.
- **Technical explanation:** Claude gave the clearer reason for using
  `date + timedelta`.
- **Test quality:** Both covered representative cases, but Claude's invariant
  and return-type tests made its test strategy more complete.
- **Fit with PawPal+:** Both approaches fit the existing data model and avoid
  creating catch-up tasks.

**Which approach did you use in your final implementation and why?**

I used the shared algorithm that both models independently produced:

```python
max(due_date, completed_on) + timedelta(days=7)
```

I selected Claude's response as the primary explanation because its invariant
provides a stronger way to verify the behavior across many dates, not just the
specific dates in the examples. I kept Gemini's examples as supporting evidence
because they explain the result in realistic scenarios.

This decision preserves the original weekly cadence when the task is completed
early or on time, gives the owner a full seven days after a late completion,
and avoids creating missed catch-up tasks. It also relies on Python's date
arithmetic rather than error-prone manual calendar calculations.

The decision did not require a code change because PawPal+ already uses this
logic in `Task.next_occurrence()`:

```python
base = max(self.due_date, today or date.today())
return replace(self, due_date=base + step, completed=False)
```

For a weekly task, `step` is `timedelta(weeks=1)`, which is equivalent to seven
days. The completed task remains in the pet's history, while the returned task
is a new pending copy with the calculated due date.
