"""Name matching for linking attempts to students after the fact (plan §14, KT-604).

Pure Python, no database access: it only reads `full_name` / `group_id` / `pk` of the students it
is given. Normalisation comes from `apps.people.names`, so apostrophe variants (Дем'ян, Дем’ян),
case and spacing never matter.

Three kinds of match, best first:

* `exact`: the normalised names are equal (what `Student.name_key` stores);
* `words`: the same words in another order ("Петро Іваненко" / "Іваненко Петро");
* `fuzzy`: `difflib` ratio of the order-independent keys is at least `FUZZY_THRESHOLD`
  (typos), or one name is the other plus extra words (a patronymic typed, or left out).

Only `exact` and `words` are confident enough to be pre-selected on the linking page;
`fuzzy` is shown as a hint for the teacher to confirm.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from apps.people.names import name_tokens, normalize_name, same_person_key

EXACT = "exact"
WORDS = "words"
FUZZY = "fuzzy"

FUZZY_THRESHOLD = 0.8
MAX_SUGGESTIONS = 3
# One name is the other plus extra words, both with at least two words: a hint, not a certainty.
SUBSET_SCORE = 0.85

_KIND_ORDER = {EXACT: 0, WORDS: 1, FUZZY: 2}


@dataclass(frozen=True)
class Suggestion:
    student: object  # anything with .pk, .full_name, .group_id
    score: float  # 1.0 exact, 0.99 same words, else the similarity ratio
    kind: str  # EXACT | WORDS | FUZZY

    @property
    def percent(self) -> int:
        return round(self.score * 100)

    @property
    def confident(self) -> bool:
        return self.kind in (EXACT, WORDS)


@dataclass(frozen=True)
class _Indexed:
    student: object
    name: str  # normalize_name(full_name)
    key: str  # same_person_key(full_name)
    tokens: frozenset


def index_students(students) -> list[_Indexed]:
    """Pre-compute the match keys once when many names are matched against the same students."""
    return [
        _Indexed(
            student=s,
            name=normalize_name(s.full_name),
            key=same_person_key(s.full_name),
            tokens=frozenset(name_tokens(s.full_name)),
        )
        for s in students
    ]


def suggest(typed_name: str, students, *, limit: int = MAX_SUGGESTIONS) -> list[Suggestion]:
    """Ranked suggestions among `students` for a typed name (best first, at most `limit`)."""
    return suggest_indexed(typed_name, index_students(students), limit=limit)


def suggest_indexed(
    typed_name: str, indexed: list[_Indexed], *, limit: int = MAX_SUGGESTIONS
) -> list[Suggestion]:
    typed = normalize_name(typed_name)
    if not typed:
        return []
    typed_key = same_person_key(typed_name)
    typed_tokens = frozenset(typed.split())
    matcher = difflib.SequenceMatcher(None, autojunk=False)
    matcher.set_seq2(typed_key)  # seq2 is analysed once and reused for every student

    found: list[Suggestion] = []
    for item in indexed:
        if item.name == typed:
            found.append(Suggestion(item.student, 1.0, EXACT))
        elif item.key == typed_key:
            found.append(Suggestion(item.student, 0.99, WORDS))
        else:
            score = _fuzzy_score(matcher, item, typed_tokens)
            if score >= FUZZY_THRESHOLD:
                found.append(Suggestion(item.student, round(score, 4), FUZZY))
    found.sort(
        key=lambda s: (
            _KIND_ORDER[s.kind],
            -s.score,
            s.student.full_name.casefold(),
            s.student.pk or 0,
        )
    )
    return found[:limit]


def _fuzzy_score(matcher: difflib.SequenceMatcher, item: _Indexed, typed_tokens) -> float:
    matcher.set_seq1(item.key)
    score = 0.0
    if matcher.real_quick_ratio() >= FUZZY_THRESHOLD and matcher.quick_ratio() >= FUZZY_THRESHOLD:
        score = matcher.ratio()
    smaller, larger = sorted((item.tokens, typed_tokens), key=len)
    if len(smaller) >= 2 and smaller < larger:
        score = max(score, SUBSET_SCORE)
    return score


def preselected(suggestions: list[Suggestion], group_id: int | None = None):
    """The student to pre-select on the linking page, or None.

    Only a single confident match qualifies (exact beats same-words). When the roster has
    several equally good matches (duplicates), the one in the session's class wins if it is
    the only one there; otherwise nothing is pre-selected and the teacher decides.
    """
    confident = [s for s in suggestions if s.confident]
    if not confident:
        return None
    best_kind = confident[0].kind
    tier = [s for s in confident if s.kind == best_kind]
    if len(tier) == 1:
        return tier[0].student
    if group_id is not None:
        in_group = [s for s in tier if getattr(s.student, "group_id", None) == group_id]
        if len(in_group) == 1:
            return in_group[0].student
    return None
