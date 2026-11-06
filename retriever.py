"""Retrieval for the AI Planner (RAG): finds the pet-care notes that apply to a request.

The knowledge base is the markdown files in knowledge/ (dogs, cats, medication: several
sources). The index is custom, in two ways:

- Section-level documents: every "## " section is its own note, so a request retrieves one
  focused paragraph, not a whole file.
- Pet-aware filtering: a comment under each heading tags the note, e.g.
  <!-- species: dog | stage: senior | keywords: walk, exercise -->. Notes are first filtered to
  the species and life stages of the pets the request names (a senior-dog note never reaches a
  plan for a young cat), then ranked by TF-IDF overlap between the request and the note's
  title, keywords and text. Keywords count double.

Standard library only: the knowledge base is small, so no vector database is needed.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Set, Tuple, Union

from pawpal_system import Owner, Pet

KNOWLEDGE_DIR = Path(__file__).parent / "knowledge"
TOP_K = 3

# From this age a pet counts as "senior". Cats age more slowly than dogs.
SENIOR_AGE = {"dog": 8, "cat": 11}
DEFAULT_SENIOR_AGE = 10
SPECIES = {"dog", "cat", "any"}
STAGES = {"young", "adult", "senior", "any"}

STOPWORDS = {
    "about", "all", "also", "any", "could", "each", "just", "like", "more", "most", "only",
    "other", "same", "should", "very", "want", "what", "when", "which", "will", "would",
    "a", "an", "and", "are", "at", "be", "but", "by", "can", "do", "for", "from", "has", "have",
    "her", "him", "his", "how", "i", "in", "into", "is", "it", "its", "me", "my", "needs", "need",
    "of", "on", "or", "our", "please", "she", "so", "some", "than", "that", "the", "their",
    "them", "then", "there", "they", "this", "to", "up", "was", "we", "with", "you", "your",
    # Species words: notes are already filtered by species, so matching on them adds nothing
    # (and made "a poem about cats" retrieve cat-care notes).
    "cat", "cats", "dog", "dogs", "pet", "pets",
}
_META = re.compile(r"<!--(.*?)-->")


@dataclass(frozen=True)
class Note:
    """One section of a knowledge file, with the tags that say who it applies to."""

    id: str  # e.g. "dogs#walks-for-senior-dogs"
    title: str
    source: str  # e.g. "knowledge/dogs.md"
    species: str  # "dog", "cat" or "any"
    stage: str  # "young", "adult", "senior" or "any"
    keywords: Tuple[str, ...]
    text: str

    def citation(self) -> str:
        """How the note is named in traces and the UI, e.g. 'Walks for senior dogs (dogs.md)'."""
        return f"{self.title} ({Path(self.source).name})"


def life_stage(species: str, age: int) -> str:
    """Return "young" (under 1), "senior" (SENIOR_AGE and over) or "adult" for a pet."""
    if age < 1:
        return "young"
    return "senior" if age >= SENIOR_AGE.get(species.lower(), DEFAULT_SENIOR_AGE) else "adult"


def stem(word: str) -> str:
    """A very small stemmer: walks/walking -> walk, meals -> meal, dogs -> dog."""
    for suffix in ("ing", "s"):
        if word.endswith(suffix) and not word.endswith("ss") and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> List[str]:
    """Lowercase words without stopwords or one- and two-letter words, stemmed."""
    return [stem(w) for w in re.findall(r"[a-z]+", text.lower()) if w not in STOPWORDS and len(w) > 2]


def parse_notes(path: Path) -> List[Note]:
    """Split one markdown file into notes, one per "## " section with a tag comment.

    Raises:
        ValueError: If a section has no tag comment or uses an unknown species or stage.
    """
    notes: List[Note] = []
    title, meta, body = None, None, []

    def flush() -> None:
        if title is None:
            return
        if meta is None:
            raise ValueError(f"{path.name}: section '{title}' has no <!-- species | stage --> tag")
        species, stage = meta.get("species", "any"), meta.get("stage", "any")
        if species not in SPECIES or stage not in STAGES:
            raise ValueError(f"{path.name}: section '{title}' has unknown species/stage tags")
        keywords = tuple(k.strip() for k in meta.get("keywords", "").split(",") if k.strip())
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
        notes.append(Note(f"{path.stem}#{slug}", title, f"knowledge/{path.name}", species, stage,
                          keywords, " ".join(" ".join(body).split())))

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            flush()
            title, meta, body = line[3:].strip(), None, []
        elif title is not None and meta is None and _META.search(line):
            pairs = (part.split(":", 1) for part in _META.search(line).group(1).split("|"))
            meta = {k.strip().lower(): v.strip().lower() for k, v in pairs}
        elif title is not None:
            body.append(line.strip())
    flush()
    return notes


def mentioned_pets(request: str, owner: Owner) -> List[Pet]:
    """The owner's pets named in the request (whole-word, any case), or all pets if none are."""
    named = [p for p in owner.pets
             if re.search(rf"\b{re.escape(p.name)}\b", request, re.IGNORECASE)]
    return named or list(owner.pets)


class KnowledgeBase:
    """The indexed notes, searchable by request and pet profile."""

    def __init__(self, notes: List[Note]) -> None:
        """Index the notes: term counts per note and an IDF weight per term."""
        self.notes = notes
        self._terms: List[Counter] = []
        self._keywords: List[Set[str]] = []
        for note in notes:
            self._terms.append(Counter(tokenize(f"{note.title} {' '.join(note.keywords)} {note.text}")))
            self._keywords.append(set(tokenize(" ".join(note.keywords))))
        doc_freq = Counter(term for terms in self._terms for term in terms)
        self._idf: Dict[str, float] = {
            term: math.log((len(notes) + 1) / (df + 1)) + 1 for term, df in doc_freq.items()}

    @classmethod
    def load(cls, folder: Union[str, Path] = KNOWLEDGE_DIR) -> "KnowledgeBase":
        """Build the knowledge base from every .md file in a folder (sorted, so it's stable)."""
        return cls([note for path in sorted(Path(folder).glob("*.md")) for note in parse_notes(path)])

    @staticmethod
    def applies(note: Note, profiles: Set[Tuple[str, str]]) -> bool:
        """True if the note is for one of these (species, life stage) profiles, or for any pet."""
        return any(note.species in ("any", species) and note.stage in ("any", stage)
                   for species, stage in profiles)

    def search(self, query: str, profiles: Iterable[Tuple[str, str]], k: int = TOP_K) -> List[Note]:
        """Rank the notes that apply to these profiles by TF-IDF overlap with the query.

        Args:
            query: The words to match, e.g. the owner's request.
            profiles: (species, life stage) pairs, e.g. {("dog", "senior")}.
            k: How many notes to return at most.

        Returns:
            Up to k notes with a score above zero, best first.
        """
        profiles = set(profiles)
        words = Counter(tokenize(query))
        scored = []
        for index, note in enumerate(self.notes):
            if not self.applies(note, profiles):
                continue
            terms, keywords = self._terms[index], self._keywords[index]
            score = sum(self._idf[w] * (1 + math.log(terms[w])) * (2 if w in keywords else 1)
                        for w in words if w in terms)
            if score > 0:
                scored.append((score, -index, note))  # -index keeps ties in file order
        return [note for _, _, note in sorted(scored, reverse=True)[:k]]

    def retrieve(self, request: str, owner: Owner, k: int = TOP_K) -> List[Note]:
        """Find the notes for a request, filtered to the pets it names (or all the owner's pets)."""
        profiles = {(p.species.lower(), life_stage(p.species, p.age))
                    for p in mentioned_pets(request, owner)}
        return self.search(request, profiles, k)


@lru_cache(maxsize=1)
def default_knowledge() -> KnowledgeBase:
    """The knowledge base in knowledge/, loaded once per process."""
    return KnowledgeBase.load()


def format_notes(notes: List[Note]) -> str:
    """The notes as a numbered block for the prompt, or "" when there are none."""
    if not notes:
        return ""
    lines = ["Care notes retrieved from the PawPal+ knowledge base for this request:"]
    lines += [f"[{n}] {note.title} ({note.source}): {note.text}"
              for n, note in enumerate(notes, start=1)]
    lines.append(
        "Follow a note when it applies to the pet: notes are more specific than the house "
        "defaults, but the owner's explicit instructions come first. In your reasoning, cite "
        "the numbers of the notes you used, like [1]."
    )
    return "\n".join(lines)
