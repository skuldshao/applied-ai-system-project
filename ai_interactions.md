# AI Interactions Log

This file records the AI side of **PawPal+ AI Planner**, my final project:

1. the AI Planner agent's saved **reasoning traces** (the Agentic Workflow stretch feature);
2. where the other evaluation logs are;
3. how I used an AI coding assistant to build the project, step by step.

The log from the original **Module 2** PawPal+ project is kept at the end as an appendix.

---

## 1. Agent reasoning traces

Every time the AI Planner runs, it records each intermediate step it took and why.
`ai_planner.save_trace()` appends the run to **[logs/agent_trace.md](logs/agent_trace.md)**, which is
committed to the repo. Each run in that file has:

- the request, the model, the prompt mode, how many care notes were retrieved, the number of model
  calls and fix rounds, and the model's confidence;
- a table with one row per step: 🛡️ Guard → 📚 Retrieve → 🧠 Plan → ✅ Validate → 🔍 Check →
  🤔 Decide → 🔧 Fix → 🧠 Revise → 🏁 Result. The Plan and Revise rows quote the model's own
  `reasoning` field, including which retrieved notes it used (`[1]`, `[2]`, …);
- the proposed tasks, the model's summary, and any problems left for the owner.

`python demo.py` regenerates the file with five runs. The Streamlit app appends a run each time the
owner clicks **Plan it**, and the same steps also go to `logs/pawpal.log`.

### Example: a conflict found and fixed by the agent (live, `python demo.py`, request 2)

Mochi already had breakfast at 07:00 when the owner asked for Luna's eye drops "at 7am". The model
kept the owner's time, the scheduler caught the clash and suggested a free slot, and the model
revised its own plan:

**Request:** Luna needs her eye drops at 7am and 9pm, and brush her this evening  
**Model:** claude-haiku-5-5 · **Prompt:** specialized · **Care notes:** 3 · **Model calls:** 2 · **Fix rounds:** 1 · **Confidence:** 0.90

| # | Step | What happened |
|---|------|---------------|
| 1 | 🛡️ Guard | Request passed the input checks. |
| 2 | 📚 Retrieve | 3 care note(s) for this request: Eye and ear drops (medication.md); Grooming adult cats (cats.md); Play for cats (cats.md) |
| 3 | 🧠 Plan | 3 task(s) drafted, confidence 0.90. Reasoning: Luna's eye drops are medication, so they use the house 5 minutes and high priority, repeating daily at the owner's 07:00 and 21:00. Note [1] applies, but Luna has only one kind of drop, so no gap is needed. The brushing has no time given, so it goes at 19:00 to avoid Mochi's 18:00 dinner, for the house 15 minutes at low priority, once. |
| 4 | ✅ Validate | 3 task(s) valid, 0 rejected. |
| 5 | 🔍 Check | 1 issue(s). 'Morning eye drops' 07:00-07:05 overlaps 'Breakfast' 07:00-07:10. The next free slot for 'Morning eye drops' is 07:15. |
| 6 | 🔧 Fix | Round 1 of 2: 1 fixable problem(s), so send the plan and the problems back to the model. |
| 7 | 🧠 Revise | 3 task(s) drafted, confidence 0.90. Reasoning: The morning eye drops move from 07:00 to 07:15, the next free slot after Mochi's breakfast and heart pill, keeping the house 5 minutes at high priority. Note [1] applies, but Luna has only one kind of drop, so no gap is needed. The other tasks stay as they were, and the total of 25 minutes fits within the 65 minutes left. |
| 8 | ✅ Validate | 3 task(s) valid, 0 rejected. |
| 9 | 🔍 Check | No conflicts, and everything fits in today's time. |
| 10 | ✅ Result | ok: 3 task(s), 0 problem(s) left, 2 model call(s). |

| Pet | Task | Time | Minutes | Priority | Repeats |
|---|---|---|---|---|---|
| Luna | Morning eye drops | 07:15-07:20 | 5 | high | daily |
| Luna | Evening eye drops | 21:00-21:05 | 5 | high | daily |
| Luna | Brushing | 19:00-19:15 | 15 | low | once |

### What the other saved runs show

The other four runs in [logs/agent_trace.md](logs/agent_trace.md) cover the other branches of the
decision chain:

| Run | Request | Decision chain |
|---|---|---|
| 1 | Feed Mochi at 7am and 6pm, and give him his heart pill with breakfast | Guard → Retrieve (pills with food, feeding dogs) → Plan → Validate → Check: clean → **ok** in 1 call |
| 3 | Take Mochi for a 60 minute walk at 10am and play fetch with him for 45 minutes at 4pm | … → Check: over the time budget → **Decide: stop**, because only the owner can choose what to drop → **needs_review** in 1 call (no wasted retries) |
| 4 | How much Benadryl can I give Mochi? | **Guard blocks** it as a dose question → refused with 0 model calls |
| 5 | Write me a poem about cats | Guard passes → Retrieve: no notes → **the model refuses** as off-topic |

## 2. Other evaluation logs

| File | What it holds | Made by |
|---|---|---|
| [logs/demo_output.txt](logs/demo_output.txt) | Full terminal output of the 5-request demo | `python demo.py` |
| [logs/eval_results.md](logs/eval_results.md) | 13 test cases × 3 runs: input, criteria, result | `python evaluate.py --runs 3` |
| [logs/eval_results_before_fix.md](logs/eval_results_before_fix.md) | The first evaluation run, which found the empty-plan bug | `python evaluate.py --runs 2` (before the fix) |
| [logs/specialization_comparison.md](logs/specialization_comparison.md) | Baseline vs. few-shot house-rules prompt | `python compare_prompts.py --runs 3` |
| [logs/rag_comparison.md](logs/rag_comparison.md) | Planning with vs. without retrieved care notes | `python compare_rag.py --runs 3` |

## 3. How I used an AI coding assistant to build this project

**Assistant used:** Claude Code (Claude Opus 5.5) in VS Code. I worked through the project one step
at a time: I asked for a step, reviewed what it built and the test or live results, made the
decisions, and then had it commit and push to `main`.

| Step | What I asked for | What the assistant did | What I decided or changed |
|---|---|---|---|
| Planning | Go through the requirements and rubric, map them to my Module 2 code | Read the codebase, ran the 92 existing tests, mapped every rubric item to a file, found repo problems (deleted `architecture.mmd`, no `.gitignore`, untracked code) | I asked for the easiest design that still earns every point; it proposed a plan → check → fix agent that reuses my Scheduler as the checker |
| 1. Clean-up | Fix the repo problems | Restored the diagram, added `.gitignore`, committed the base project | I told it to always commit to `main` and push after every step, not to use a feature branch |
| 2. LLM client | Connect Claude | `llm_client.py` with a real client and a `FakeLLM` for offline tests, logging, `.env.example` | I chose Claude Haiku 5.5 over Opus for cost and speed; I asked for much more detailed commit messages, and it rewrote the commit |
| 3. Agent | Build the AI feature | `ai_planner.py` + `prompts.py`; ran it live | The first design idea, a full tool-calling agent, was scaled down to a JSON plan → check → fix loop |
| 4. Specialization | Few-shot house rules | `house_rules.py`, `compare_prompts.py`; live comparison | Measured 73% → 100% rule compliance; found that the baseline wrongly refused a heart-pill request |
| 5. UI and demo | Put it in the app | Streamlit AI Planner with Approve/Reject, `demo.py`; drove the app headlessly | Nothing is saved until I approve, so a person always checks the AI's plan |
| 6. Evaluation | Test reliability | `evaluate.py`; its first run found a real bug (an empty plan read as "nothing to plan") | Reviewed the fix and the measurement that cut wasted retries from 2 to 1 |
| 7. RAG | Retrieval bonus | `knowledge/` notes, `retriever.py`, `compare_rag.py` | Measured 33% → 100% of plans following the relevant care note |
| 8. Write-up | Diagram, README, model card, this file | Drafted all four from the real code and logs | I reviewed and edited the reflections (see `model_card.md`) |

The accepted and rejected suggestions, and what I learned from working this way, are in
[model_card.md](model_card.md#ai-collaboration).

---

## Appendix: Module 2 AI interactions (original PawPal+)

### Agent Workflow (SF7)

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

### Prompt Comparison (SF11)

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

#### Why this task is algorithmically interesting

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

#### Detailed evaluation of Option A: Claude Sonnet 5

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

#### Detailed evaluation of Option B: Gemini 3.8 Flash

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

#### Direct comparison

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
