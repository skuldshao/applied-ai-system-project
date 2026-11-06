from datetime import time
from pathlib import Path

import streamlit as st

from ai_planner import PlanResult, TraceStep, apply_plan, plan_request, save_trace
from formatting import STATUS_BADGE, priority_badge, status_badge, task_label
from llm_client import ClaudeClient, LLMError
from pawpal_logging import setup_logging
from pawpal_system import Owner, Pet, Scheduler, Task

# Saved next to app.py, so the same file is used no matter which folder the app starts from.
DATA_FILE = Path(__file__).parent / "data.json"

setup_logging()  # logs/pawpal.log; safe to call on every rerun
st.set_page_config(page_title="PawPal+", page_icon="🐾", layout="centered")

st.title("🐾 PawPal+")
st.caption(
    "Plan your pets' day. Add tasks yourself, or describe what your pets need and let the "
    "🤖 AI Planner draft them. PawPal+ checks every AI plan for clashes and for time, and "
    "nothing the AI suggests is saved until you approve it."
)

st.divider()

# --- Owner -----------------------------------------------------------------------
# The owner's name and daily time budget. available_minutes is what the Scheduler
# uses to decide how many tasks fit into today's plan.

# Streamlit reruns this script on every interaction, so keep one Owner in session_state.
# The first time, load it from data.json so pets and tasks survive restarting the app;
# afterwards reuse the stored instance. Owner.load_from_json() returns None on the first
# run (no file yet), and raises ValueError if the file is damaged.
if "owner" not in st.session_state:
    try:
        st.session_state.owner = Owner.load_from_json(DATA_FILE) or Owner(
            name="Jordan", available_minutes=90
        )
    except ValueError as err:
        st.session_state.owner = Owner(name="Jordan", available_minutes=90)
        st.error(f"Couldn't read saved data, starting fresh. {err}")
owner = st.session_state.owner


def save() -> None:
    """Write the owner, pets and tasks to data.json. Called after every change."""
    owner.save_to_json(DATA_FILE)


st.subheader("Owner")
# The widgets start from the loaded Owner, so a returning user sees their own name and time.
owner_name = st.text_input("Owner name", value=owner.name)
available_minutes = st.number_input(
    "Minutes available today", min_value=0, max_value=1440,
    value=owner.available_minutes, step=5,
)
# Copy the latest widget values onto the stored Owner so edits take effect immediately,
# and save only when something actually changed.
if (owner_name, int(available_minutes)) != (owner.name, owner.available_minutes):
    owner.name = owner_name
    owner.available_minutes = int(available_minutes)
    save()
st.caption(f"💾 Pets and tasks are saved automatically to `{DATA_FILE.name}`.")

# The Scheduler holds no data of its own; it reads everything through
# owner.get_all_tasks(), so it is cheap to rebuild on every rerun and always sees every pet.
scheduler = Scheduler(owner)

st.divider()

# --- Add a pet -------------------------------------------------------------------
# st.form groups the inputs so typing in them doesn't rerun the app; only clicking
# "Add pet" submits. clear_on_submit resets the fields after a successful add.

st.subheader("Pets")
with st.form("add_pet", clear_on_submit=True):
    col1, col2, col3 = st.columns(3)
    with col1:
        pet_name = st.text_input("Pet name", value="Mochi")
    with col2:
        species = st.selectbox("Species", ["dog", "cat", "other"])
    with col3:
        age = st.number_input("Age (years)", min_value=0, max_value=40, value=3)
    if st.form_submit_button("Add pet"):
        # Validate before touching the Owner: reject blank names, and use
        # Owner.find_pet() to block duplicates (pets are looked up by name later).
        if not pet_name.strip():
            st.error("Please enter a pet name.")
        elif owner.find_pet(pet_name.strip()):
            st.error(f"{pet_name.strip()} is already one of your pets.")
        else:
            # Owner.add_pet() owns this change: the Owner is the class that manages
            # multiple pets. Because the Owner lives in session_state, the new Pet survives
            # the rerun that Streamlit triggers right after this button click.
            owner.add_pet(Pet(name=pet_name.strip(), species=species, age=int(age)))
            save()
            st.success(f"Added {pet_name.strip()}!")

# Drawn after the form, so on the rerun triggered by "Add pet" this table already
# reads the updated owner.pets and shows the new pet; no manual refresh is needed.
if owner.pets:
    st.table(
        [
            {"Pet": p.name, "Species": p.species, "Age": p.age, "Tasks": len(p.tasks)}
            for p in owner.pets
        ]
    )
else:
    st.info("No pets yet. Add one above.")

st.divider()

# --- AI Planner ------------------------------------------------------------------
# The owner types a request in plain English. ai_planner.plan_request() drafts tasks with
# Claude, checks them with the same Scheduler used further down this page, sends fixable
# problems back to Claude, and returns a plan. The plan is kept in session_state (Streamlit
# reruns on every click) and nothing is saved until the owner clicks Approve.

STATUS_HEADLINES = {
    "ok": "✅ Plan ready for your approval",
    "needs_review": "⚠️ Plan needs your review",
    "refused": "🛡️ Request not planned",
    "error": "❌ The AI Planner hit an error",
}


@st.cache_resource
def planner_client() -> ClaudeClient:
    """One Claude client for the app (reads ANTHROPIC_API_KEY from .env)."""
    return ClaudeClient()


def show_plan(result: PlanResult) -> None:
    """Show a finished plan: numbers, proposed tasks, problems, Approve/Reject, and the trace."""
    if result.status in ("refused", "error"):
        (st.info if result.status == "refused" else st.error)(
            f"{STATUS_HEADLINES[result.status]}: {result.message}")
        if st.button("Clear"):
            del st.session_state.ai_result
            st.rerun()
    else:
        st.markdown(f"**{STATUS_HEADLINES[result.status]}**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Tasks", len(result.tasks))
        c2.metric("Model calls", result.llm_calls)
        c3.metric("Fix rounds", result.fix_rounds)
        c4.metric("Confidence", f"{result.confidence:.0%}")
        if result.summary:
            st.markdown(f"💬 {result.summary}")
        st.table([
            {
                "Time": p.task.time_window(),
                "Pet": p.pet_name,
                "Task": task_label(p.task),
                "Minutes": p.task.duration_minutes,
                "Priority": priority_badge(p.task.priority),
                "Repeats": p.task.frequency,
            }
            for p in result.tasks
        ])
        for problem in result.problems:
            st.warning(problem.message)
        approve, reject = st.columns(2)
        label = "✅ Approve and add" if result.status == "ok" else "⚠️ Approve anyway"
        if approve.button(label, type="primary"):
            added = apply_plan(owner, result)
            save()
            st.session_state.ai_flash = f"Added {added} task(s) from the AI plan."
            del st.session_state.ai_result
            st.rerun()
        if reject.button("🗑️ Reject"):
            st.session_state.ai_flash = "Plan discarded. Nothing was changed."
            del st.session_state.ai_result
            st.rerun()
    with st.expander("🧠 How the AI got here (agent trace)"):
        st.table([{"Step": f"{s.icon} {s.name}", "What happened": s.detail} for s in result.trace])
        st.caption(f"Model: {result.model} · prompt: {result.prompt_mode} · "
                   "every run is also saved to logs/agent_trace.md")


st.subheader("🤖 AI Planner")
st.caption(
    "Describe what your pets need, e.g. *Feed Mochi at 7am and 6pm, and give him his heart pill "
    "with breakfast*. The AI drafts tasks using PawPal+'s house rules, the scheduler checks them "
    "for clashes and time, and you approve before anything is saved."
)
if "ai_flash" in st.session_state:
    st.success(st.session_state.pop("ai_flash"))

if not owner.pets:
    st.caption("Add a pet first, then the AI Planner can plan for it.")
else:
    try:
        client = planner_client()
    except LLMError as err:
        client = None
        st.error(f"{err} The rest of PawPal+ still works without it.")
    if client is not None:
        with st.form("ai_planner"):
            ai_request = st.text_area("What do your pets need?", height=80,
                                      placeholder="Walk Mochi at 7am and brush Luna this evening")
            submitted = st.form_submit_button("✨ Plan it", type="primary")
        if submitted:
            with st.status("🤖 Planning…", expanded=True) as status:

                def show_step(step: TraceStep) -> None:
                    st.write(f"{step.icon} **{step.name}** · {step.detail}")

                result = plan_request(owner, ai_request, client, on_step=show_step)
                save_trace(result)
                status.update(label=STATUS_HEADLINES[result.status], expanded=False,
                              state="error" if result.status == "error" else "complete")
            st.session_state.ai_result = result
        if "ai_result" in st.session_state:
            show_plan(st.session_state.ai_result)

st.divider()

# --- Schedule a task ---------------------------------------------------------------
# Tasks always belong to a specific Pet, so this form only appears once a pet exists.

st.subheader("Tasks")
if not owner.pets:
    st.caption("Add a pet first, then you can schedule tasks for it.")
else:
    with st.form("add_task", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            # Options come from owner.pets, so newly added pets appear here automatically.
            task_pet = st.selectbox("Pet", [p.name for p in owner.pets])
            description = st.text_input("Task", value="Morning walk")
            # step=900 seconds gives 15-minute increments in the time picker.
            start_time = st.time_input("Start time", value=time(8, 0), step=900)
        with col2:
            duration = st.number_input(
                "Duration (minutes)", min_value=1, max_value=240, value=20
            )
            priority = st.selectbox("Priority", ["low", "medium", "high"], index=2)
            frequency = st.selectbox("Frequency", ["once", "daily", "weekly"], index=1)
        if st.form_submit_button("Add task"):
            # Look up the chosen Pet by name, then call Pet.add_task() with a new Task.
            # Task.__post_init__ validates priority, frequency, and duration; if any value
            # is invalid it raises ValueError, which we show in the UI instead of crashing.
            try:
                owner.find_pet(task_pet).add_task(
                    Task(
                        description=description.strip(),
                        start_time=start_time,
                        duration_minutes=int(duration),
                        priority=priority,
                        frequency=frequency,
                    )
                )
                save()
                st.success(f"Added '{description.strip()}' for {task_pet}.")
            except ValueError as err:
                st.error(str(err))

    # Mark a pending task done. Scheduler.mark_task_complete() also adds the next copy of a
    # daily or weekly task, so it appears in the table below with its new due date.
    pending = scheduler.sort_by_time(scheduler.get_tasks(completed=False))
    if pending:
        with st.form("complete_task"):
            choice = st.selectbox(
                "Mark a task done",
                range(len(pending)),
                format_func=lambda i: (
                    f"{pending[i][0].name}: {task_label(pending[i][1])} "
                    f"(due {pending[i][1].due_date:%b %d}, {pending[i][1].frequency})"
                ),
            )
            if st.form_submit_button("Mark done"):
                pet, task = pending[choice]
                scheduler.mark_task_complete(pet.name, task.description)
                save()
                # For a recurring task, the new pending copy is the next occurrence.
                nxt = pet.find_task(task.description, pending_only=True)
                if nxt is not None:
                    st.success(
                        f"Done! Next '{task.description}' for {pet.name} is due "
                        f"{nxt.due_date:%a %b %d}."
                    )
                else:
                    st.success(f"Done! '{task.description}' for {pet.name} is complete.")

    # --- Browse tasks: filter and sort --------------------------------------------
    # The filters map straight onto Scheduler.get_tasks(pet_name, completed), and the sort
    # choice picks Scheduler.sort_by_time() or Scheduler.sort_by_priority().
    st.markdown("#### All tasks")
    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        pet_filter = st.selectbox("Filter by pet", ["All pets"] + [p.name for p in owner.pets])
    with fcol2:
        status_filter = st.selectbox("Filter by status", ["All", "Pending", "Done"])
    with fcol3:
        sort_choice = st.selectbox("Sort by", ["Time", "Priority"])

    filtered = scheduler.get_tasks(
        pet_name=None if pet_filter == "All pets" else pet_filter,
        completed={"All": None, "Pending": False, "Done": True}[status_filter],
    )
    if sort_choice == "Time":
        filtered = scheduler.sort_by_time(filtered)
    else:
        filtered = scheduler.sort_by_priority(filtered)

    if filtered:
        st.table(
            [
                {
                    "Due": t.due_date.strftime("%a %b %d"),
                    "Time": t.start_time.strftime("%H:%M"),
                    "Pet": p.name,
                    "Task": task_label(t),
                    "Minutes": t.duration_minutes,
                    "Priority": priority_badge(t.priority),
                    "Frequency": t.frequency,
                    "Status": status_badge(t),
                }
                for p, t in filtered
            ]
        )
        st.caption(
            f"Showing {len(filtered)} of {len(scheduler.get_tasks())} tasks, "
            f"sorted by {sort_choice.lower()}.  \n"
            # Legend for the badges, built from the same dicts the badges use.
            f"Priority: {' · '.join(priority_badge(p) for p in ('high', 'medium', 'low'))}"
            f"  |  Status: {' · '.join(STATUS_BADGE.values())}"
        )
    elif scheduler.get_tasks():
        st.info("No tasks match these filters.")
    else:
        st.info("No tasks yet. Add one above.")

st.divider()

# --- Build schedule --------------------------------------------------------------
# Runs the Scheduler's planning logic and explains the result: which tasks overlap,
# what was scheduled, and what was skipped for lack of time. It is rebuilt on every rerun,
# so it updates as soon as a task is added or marked done.

st.subheader("Today's Schedule")

# todays_schedule() takes pending tasks due today or earlier in priority order
# (high -> low) and keeps each one that still fits in available_minutes. Future copies of
# recurring tasks wait for their day. The order choice only changes how the kept tasks are
# listed: as a timeline, or most important first (priority, then time).
plan_order = st.radio(
    "Show plan by", ["Time", "Priority"], horizontal=True,
    help="Priority lists high → low, then by time. Either way, priority decides what fits.",
)
schedule = scheduler.todays_schedule(order=plan_order.lower())
skipped = scheduler.skipped_tasks()
conflicts = scheduler.find_conflicts()

if not schedule:
    if skipped:
        st.warning("None of today's tasks fit in your available time. Try adding more minutes.")
    else:
        st.info("Nothing due today. Add some tasks, or check back when the next ones are due.")
else:
    used = sum(t.duration_minutes for _, t in schedule)
    m1, m2, m3 = st.columns(3)
    m1.metric("Tasks planned", len(schedule))
    m2.metric("Minutes used", f"{used} / {owner.available_minutes}")
    m3.metric("Conflicts", len(conflicts))
    # Same idea as the CLI's budget bar: how much of today's free time the plan uses.
    st.progress(
        min(used / owner.available_minutes, 1.0) if owner.available_minutes else 0.0,
        text=f"Time budget: {used} of {owner.available_minutes} min",
    )

    # Conflicts come first: they are the one problem the owner must fix before the day starts.
    # Each one gets the Scheduler's message plus a concrete fix: the next free slot for the
    # later task, found by Scheduler.find_next_available_slot() so the fix can't clash with
    # some other task.
    if conflicts:
        st.warning(
            f"**{len(conflicts)} timing conflict{'s' if len(conflicts) > 1 else ''}:** "
            "you can't be in two places at once. Move one task in each pair below."
        )
        for warning, ((pet_a, a), (pet_b, b)) in zip(scheduler.conflict_warnings(), conflicts):
            # Search from when the earlier task ends; ignore=b so b doesn't block its own move.
            # A task ending past midnight leaves no room later today, so there's no suggestion.
            slot = (
                scheduler.find_next_available_slot(
                    b.duration_minutes,
                    earliest=time(a.end_minute // 60, a.end_minute % 60),
                    latest=time(23, 59),
                    ignore=b,
                )
                if a.end_minute < 24 * 60
                else None
            )
            tip = (
                f"💡 Next free slot for {pet_b.name}'s '{b.description}': **{slot:%H:%M}**."
                if slot
                else f"💡 No free slot left today for {pet_b.name}'s '{b.description}'."
            )
            st.markdown(f"- {warning.replace('⚠️', '').strip()}  \n  {tip}")
    else:
        st.success("No overlapping tasks. Your plan is conflict-free.")

    # Flag conflicting rows in the table too, so the owner can see them in context.
    clashing = {id(t) for pair in conflicts for _, t in pair}
    st.table(
        [
            {
                "Time": t.time_window(),
                "Pet": p.name,
                "Task": task_label(t),
                "Minutes": t.duration_minutes,
                "Priority": priority_badge(t.priority),
                "Clash": "⚡" if id(t) in clashing else "",
            }
            for p, t in schedule
        ]
    )

    # Next available slot: the earliest gap in today's plan that fits a task of this length,
    # so the owner can add something new without creating a conflict.
    with st.expander("🔎 Find a free slot"):
        scol1, scol2, scol3 = st.columns(3)
        with scol1:
            slot_minutes = st.number_input(
                "Task length (minutes)", min_value=1, max_value=240, value=20, key="slot_len"
            )
        with scol2:
            slot_from = st.time_input("Not before", value=time(6, 0), step=900)
        with scol3:
            slot_until = st.time_input("Finish by", value=time(22, 0), step=900)
        slot = scheduler.find_next_available_slot(
            int(slot_minutes), earliest=slot_from, latest=slot_until
        )
        if slot:
            st.success(f"The next free {int(slot_minutes)}-minute slot starts at **{slot:%H:%M}**.")
        else:
            st.warning("No gap that long between those times. Try a shorter task or a wider window.")

    # Explain the plan in plain language so the user knows how tasks were chosen.
    st.caption(
        "Why this plan: pending tasks were picked from high to low priority "
        "until your available time ran out, then ordered by "
        + ("start time." if plan_order == "Time" else "priority, then start time.")
    )

# Pending tasks that didn't fit the time budget (usually lower-priority ones).
if skipped:
    with st.expander(f"Skipped today ({len(skipped)}): not enough time", expanded=True):
        st.table(
            [
                {
                    "Time": t.start_time.strftime("%H:%M"),
                    "Pet": p.name,
                    "Task": task_label(t),
                    "Minutes": t.duration_minutes,
                    "Priority": priority_badge(t.priority),
                }
                for p, t in skipped
            ]
        )
        st.caption("Raise your available minutes above to fit these in.")
