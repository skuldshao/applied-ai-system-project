"""Tests for the knowledge base, the retriever, and how the planner uses retrieved notes."""

import pytest

from ai_planner import plan_request
from llm_client import FakeLLM
from pawpal_system import Owner, Pet
from retriever import (
    KnowledgeBase,
    Note,
    SPECIES,
    STAGES,
    default_knowledge,
    format_notes,
    life_stage,
    mentioned_pets,
    parse_notes,
    stem,
    tokenize,
)
from sample_data import sample_owner


@pytest.fixture
def owner():
    """Mochi (dog, 3), Luna (cat, 5) and Rocky, a senior dog (12)."""
    o = sample_owner()
    o.add_pet(Pet(name="Rocky", species="dog", age=12))
    return o


def titles(notes):
    return [n.title for n in notes]


# --- Parsing and the custom index ------------------------------------------------------


def test_parse_notes_splits_sections_and_reads_tags(tmp_path):
    path = tmp_path / "test.md"
    path.write_text(
        "# Title\nIntro text is ignored.\n\n"
        "## Walks for senior dogs\n<!-- species: dog | stage: senior | keywords: walk, old -->\n"
        "Keep walks short,\nabout 20 minutes.\n\n"
        "## Any pet\n<!-- species: any | stage: any -->\nGeneral note.\n", encoding="utf-8")
    first, second = parse_notes(path)
    assert first == Note("test#walks-for-senior-dogs", "Walks for senior dogs", "knowledge/test.md",
                         "dog", "senior", ("walk", "old"), "Keep walks short, about 20 minutes.")
    assert (second.species, second.stage, second.keywords) == ("any", "any", ())


@pytest.mark.parametrize("text, problem", [
    ("## No tag\nJust text.\n", "has no"),
    ("## Bad\n<!-- species: fish | stage: any -->\nText.\n", "unknown species"),
])
def test_parse_notes_rejects_untagged_or_badly_tagged_sections(tmp_path, text, problem):
    path = tmp_path / "bad.md"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=problem):
        parse_notes(path)


def test_real_knowledge_base_has_valid_notes_from_several_sources():
    kb = default_knowledge()
    assert len(kb.notes) >= 12
    assert {n.source for n in kb.notes} == {
        "knowledge/dogs.md", "knowledge/cats.md", "knowledge/medication.md"}
    assert len({n.id for n in kb.notes}) == len(kb.notes)
    assert all(n.species in SPECIES and n.stage in STAGES and n.text for n in kb.notes)


def test_knowledge_notes_never_give_doses():
    # Matches the input guard: PawPal+ schedules medicine but never advises on amounts.
    for note in default_knowledge().notes:
        assert " mg" not in note.text and " ml" not in note.text, note.title


@pytest.mark.parametrize("species, age, stage", [
    ("dog", 0, "young"), ("dog", 3, "adult"), ("dog", 8, "senior"),
    ("cat", 10, "adult"), ("cat", 11, "senior"), ("rabbit", 10, "senior"), ("Dog", 9, "senior"),
])
def test_life_stage(species, age, stage):
    assert life_stage(species, age) == stage


def test_tokenize_stems_and_drops_stopwords_and_species_words():
    assert stem("walks") == "walk" and stem("walking") == "walk" and stem("grass") == "grass"
    # "the", "their" and "about" are stopwords, "dogs" is a species word, and "8am" loses its
    # digit, leaving "am", which is too short to keep.
    assert tokenize("Walk the dogs after their meals, about 8am") == ["walk", "after", "meal"]


def test_mentioned_pets_uses_named_pets_or_all(owner):
    assert [p.name for p in mentioned_pets("Walk ROCKY now", owner)] == ["Rocky"]
    assert [p.name for p in mentioned_pets("Feed everyone", owner)] == ["Mochi", "Luna", "Rocky"]
    assert mentioned_pets("Walk Mochiko", owner) == owner.pets  # whole words only


# --- Retrieval -----------------------------------------------------------------------


def test_senior_dog_gets_the_senior_walk_note(owner):
    notes = default_knowledge().retrieve("Take Rocky for a walk every morning", owner)
    assert notes[0].title == "Walks for senior dogs"
    assert "Walks for adult dogs" not in titles(notes)


def test_adult_dog_never_gets_senior_or_puppy_notes(owner):
    notes = default_knowledge().retrieve("Take Mochi for a walk", owner)
    assert "Walks for adult dogs" in titles(notes)
    assert not {"Walks for senior dogs", "Walks for puppies"} & set(titles(notes))


def test_cat_request_gets_no_dog_notes(owner):
    notes = default_knowledge().retrieve("Feed Luna at 7 and 6pm", owner)
    assert titles(notes) == ["Feeding cats"]


@pytest.mark.parametrize("request_text, first", [
    ("Luna needs her insulin twice a day", "Insulin for diabetic pets"),
    ("Luna needs her eye drops at 9am and 9pm", "Eye and ear drops"),
    ("Clean Luna's litter box", "Litter box"),
    ("Walk Mochi this afternoon", "Walks in hot weather"),
    ("Feed Mochi at 7am and take him for a walk after breakfast", "Exercise after meals"),
])
def test_best_note_ranks_first(owner, request_text, first):
    assert default_knowledge().retrieve(request_text, owner)[0].title == first


@pytest.mark.parametrize("request_text", ["Write me a poem about cats", "What's the capital of France?"])
def test_off_topic_requests_retrieve_nothing(owner, request_text):
    assert default_knowledge().retrieve(request_text, owner) == []


def test_search_returns_at_most_k_notes():
    kb = default_knowledge()
    assert len(kb.search("walk meal feed play", {("dog", "adult")}, k=2)) == 2


def test_format_notes_numbers_notes_and_asks_for_citations():
    note = Note("x#a", "A note", "knowledge/x.md", "any", "any", (), "Do the thing.")
    text = format_notes([note, note])
    assert "[1] A note (knowledge/x.md): Do the thing." in text and "[2] A note" in text
    assert "cite the numbers" in text
    assert format_notes([]) == ""


# --- The planner uses what it retrieves -------------------------------------------------


def walk_reply():
    return {"refuse": False, "refuse_reason": "", "reasoning": "Used [1].", "summary": "s",
            "confidence": 0.9, "tasks": [{"pet_name": "Rocky", "description": "Morning walk",
                                          "start_time": "08:00", "duration_minutes": 20,
                                          "priority": "medium", "frequency": "daily"}]}


def test_planner_retrieves_notes_and_puts_them_in_the_prompt(owner):
    fake = FakeLLM([walk_reply()])
    result = plan_request(owner, "Walk Rocky every morning", fake)
    assert result.notes[0] == "Walks for senior dogs (dogs.md)"
    assert [s.name for s in result.trace][:3] == ["Guard", "Retrieve", "Plan"]
    prompt = fake.calls[0]["prompt"]
    assert "[1] Walks for senior dogs (knowledge/dogs.md): Dogs aged 8 and over" in prompt
    # The notes come before the owner's request, and the system prompt is unchanged.
    assert prompt.index("Care notes retrieved") < prompt.index("Owner's request")


def test_fix_prompts_keep_the_same_notes(owner):
    bad = walk_reply()
    bad["tasks"][0]["duration_minutes"] = 0
    fake = FakeLLM([bad, walk_reply()])
    plan_request(owner, "Walk Rocky every morning", fake)
    assert "[1] Walks for senior dogs" in fake.calls[1]["prompt"]


def test_retrieval_can_be_switched_off_for_comparisons(owner):
    fake = FakeLLM([walk_reply()])
    result = plan_request(owner, "Walk Rocky every morning", fake, use_knowledge=False)
    assert result.notes == [] and not result.retrieval
    assert "Retrieve" not in [s.name for s in result.trace]
    assert "Care notes retrieved" not in fake.calls[0]["prompt"]


def test_no_matching_notes_is_reported_in_the_trace():
    o = Owner(name="Sam")
    o.add_pet(Pet(name="Bubbles", species="fish", age=1))
    result = plan_request(o, "Feed Bubbles", FakeLLM([walk_reply()]),
                          knowledge=KnowledgeBase([]))
    assert result.trace[1].detail == "No care notes match this request."
