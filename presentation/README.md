# Presentation: PawPal+ AI Planner

The 5–7 minute final-project presentation: 13 slides with a live demo, about 6.5 minutes.

| File | What it is |
|---|---|
| [speaker_notes.md](speaker_notes.md) | The full talk script, slide by slide, with target times |
| [deck/deck.json](deck/deck.json) | The deck index: title, slide order, sections, fonts |
| [deck/slides/](deck/slides/) | One HTML file per slide (source) |

**Live deck:** <https://claude.ai/artifact/BR6PzqiiRLX17EMejAcuTW>. It can be presented and
downloaded as PowerPoint or PDF from that page. It opens only for people it has been shared with.

## Slides

| # | Slide | What it shows | Time |
|---|---|---|---|
| 1 | PawPal+ AI Planner | Title | 0:20 |
| 2 | PawPal+ (Module 2): no AI yet | The base project: pets and tasks, daily plan, clash checks, 92 tests | 0:30 |
| 3 | On its own, the AI is confidently wrong in small ways | Five real mistakes Claude Haiku made in testing | 0:35 |
| 4 | The AI proposes. Tested code decides. A human approves. | The core idea | 0:20 |
| 5 | How a request flows | Guard → Retrieve → Plan → Validate → Check → Decide → Approve, with the fix loop | 0:45 |
| 6 | The agent catches its own clash | Live demo: Luna's 7:00 drops clash with Mochi's breakfast and are moved to 07:15 | 1:00 |
| 7 | The right advice for the right pet | RAG: 33% → 100% of plans follow the care note; 12-year-old Rocky's walks | 0:35 |
| 8 | House rules from three examples | Specialization: 73% → 100% house-rule compliance; wrong refusals 3 → 0 | 0:30 |
| 9 | Guardrails in layers | Input guard, model refusal, validation, Decide step, human approval | 0:30 |
| 10 | My own evaluation found a real bug | 11/12 → fix → 13/13 cases, 39/39 runs | 0:35 |
| 11 | Four lessons | Confidence isn't a check; safety rules can overshoot; repeat tests; reuse what you trust | 0:30 |
| 12 | What it can't do yet, and what's next | Honest limits and next steps | 0:20 |
| 13 | What this project says about me | Closing and questions | 0:20 |

## Where the numbers come from

Every figure on the slides comes from a committed report in [`../logs/`](../logs/):

| Slide | Source |
|---|---|
| 3, 6 | [demo_output.txt](../logs/demo_output.txt), [agent_trace.md](../logs/agent_trace.md), [rag_comparison.md](../logs/rag_comparison.md), [specialization_comparison.md](../logs/specialization_comparison.md) |
| 7 | [rag_comparison.md](../logs/rag_comparison.md) |
| 8 | [specialization_comparison.md](../logs/specialization_comparison.md) |
| 9 | [eval_results.md](../logs/eval_results.md), plus the guard tests described in [model_card.md](../model_card.md#limitations-and-biases) |
| 10 | [eval_results_before_fix.md](../logs/eval_results_before_fix.md) and [eval_results.md](../logs/eval_results.md) |

## Running the live demo (slide 6)

```bash
source .venv/bin/activate
streamlit run app.py
```

Add Mochi (dog) and Luna (cat) and schedule Mochi's breakfast at 07:00, either through the AI
Planner ("Feed Mochi at 7am and 6pm, and give him his heart pill with breakfast") or the Tasks form.
Then ask: *"Luna needs her eye drops at 7am and 9pm, and brush her this evening."* For a run that
doesn't depend on the live API, `python demo.py` plays the same scenario in the terminal; slide 6
shows the recorded run.

## About the slide files

The slides are in the Claude Slides format: each file is one `<section>` on a 1920×1080 canvas
with inline styles, and the speaker notes are in its `<aside>`. A few elements (`<x-icon>`,
`<x-shape>`, `<x-connector>`) are drawn by the Slides viewer, so open the live deck or a PDF/PPTX
export to see the slides as designed rather than opening the HTML files directly in a browser.
