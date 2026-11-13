"""Test Document v1 (plan §11): pydantic models, structural validation only.

Semantic checks (exactly one correct option, unique ids, ...) live in `importer.py`, because they
need generated ids and produce friendlier, path-based messages. Unknown fields are ignored here;
the importer warns about them by walking the raw data against these models' field names.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

FORMAT_NAME = "knowledge-tester/test"
FORMAT_VERSION = 1

QuestionType = Literal["single_choice", "multiple_choice", "choose_n", "short_answer", "open"]
CHOICE_TYPES = ("single_choice", "multiple_choice", "choose_n")
ScoringMode = Literal["partial", "all_or_nothing", "per_option"]
ShortAnswerMode = Literal["text", "numeric"]
ShowResult = Literal["none", "score", "full"]
GradeScale = Literal["percent", "points", "pass_fail", "ua_12", "five_point", "custom"]

# Which optional question fields each type actually uses (besides the common ones).
COMMON_QUESTION_FIELDS = frozenset({"id", "type", "text", "points", "required", "hint", "image"})
TYPE_FIELDS: dict[str, frozenset[str]] = {
    "single_choice": frozenset({"options", "penalty"}),
    "multiple_choice": frozenset({"options", "scoring"}),
    "choose_n": frozenset({"options", "n"}),
    "short_answer": frozenset(
        {"mode", "accept", "case_sensitive", "tolerance", "review_unmatched"}
    ),
    "open": frozenset({"rubric"}),
}


def _id_to_str(value: Any) -> Any:
    """LLMs sometimes write numeric ids (1, 2); accept them as text."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)


class Option(_Base):
    id: str | None = Field(None, min_length=1, max_length=40)
    text: str = Field(min_length=1, max_length=1000)
    correct: bool = False
    weight: float | None = Field(None, allow_inf_nan=False, ge=-1_000_000, le=1_000_000)

    _coerce_id = field_validator("id", mode="before")(_id_to_str)


class Question(_Base):
    id: str | None = Field(None, min_length=1, max_length=40)
    type: QuestionType
    text: str = Field(min_length=1, max_length=5000)
    points: float = Field(1, ge=0, le=1_000_000, allow_inf_nan=False)
    required: bool = False
    hint: str | None = None
    image: str | None = None
    options: list[Option] | None = None
    scoring: ScoringMode | None = None
    penalty: float | None = Field(None, ge=0, le=1, allow_inf_nan=False)
    n: int | None = Field(None, ge=1)
    mode: ShortAnswerMode | None = None
    accept: list[str] | None = None
    case_sensitive: bool | None = None
    tolerance: float | None = Field(None, ge=0, le=1e12, allow_inf_nan=False)
    review_unmatched: bool | None = None
    rubric: str | None = None

    _coerce_id = field_validator("id", mode="before")(_id_to_str)

    @field_validator("points")
    @classmethod
    def _points_in_halves(cls, value: float) -> float:
        if (value * 2) != int(value * 2):
            raise ValueError("must be a multiple of 0.5 (for example 1, 1.5 or 2)")
        return value

    @field_validator("accept", mode="before")
    @classmethod
    def _accept_numbers_as_text(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        out: list[Any] = []
        for item in value:
            if isinstance(item, bool):
                out.append(item)
            elif isinstance(item, float):
                out.append(format(item, "g"))
            elif isinstance(item, int):
                out.append(str(item))
            else:
                out.append(item)
        return out


class Settings(_Base):
    time_limit_minutes: int | None = Field(None, ge=1)
    shuffle_questions: bool = False
    shuffle_options: bool = False
    one_question_per_page: bool = False
    show_result: ShowResult = "score"
    max_attempts: int = Field(1, ge=1)


class TakerField(_Base):
    key: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=100)
    required: bool = False


class Threshold(_Base):
    min_percent: float = Field(ge=0, le=100, allow_inf_nan=False)
    label: str = Field(min_length=1, max_length=40)

    @field_validator("label", mode="before")
    @classmethod
    def _label_to_str(cls, value: Any) -> Any:
        return _id_to_str(value)


class Grading(_Base):
    enabled: bool = True
    scale: GradeScale = "percent"
    pass_percent: float = Field(50, ge=0, le=100, allow_inf_nan=False)
    thresholds: list[Threshold] | None = None


def _default_taker_fields() -> list[TakerField]:
    return [TakerField(key="name", label="Full name", required=True)]


class TestBody(_Base):
    __test__ = False  # not a pytest class

    title: str = Field(min_length=1, max_length=200)
    description: str = ""
    language: str = Field("en", min_length=2, max_length=8)
    settings: Settings = Field(default_factory=Settings)
    taker_fields: list[TakerField] = Field(default_factory=_default_taker_fields)
    grading: Grading = Field(default_factory=Grading)
    questions: Annotated[list[Question], Field(min_length=1, max_length=200)]


class TestDocument(_Base):
    __test__ = False  # not a pytest class

    format: Literal["knowledge-tester/test"]
    version: Literal[1]
    test: TestBody
