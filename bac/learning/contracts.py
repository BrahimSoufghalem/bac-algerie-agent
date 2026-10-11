from typing import Literal, Annotated
from pydantic import Field, model_validator
from bac.agent.models import Strict, Answer

Short = Annotated[str, Field(min_length=1, max_length=100)]


class Preferences(Strict):
    track: str = Field(default="", max_length=100)
    subjects: list[Short] = Field(default_factory=list, max_length=8)
    language: Literal["ar", "fr", "en"] = "ar"
    detail: Literal["brief", "balanced", "deep"] = "balanced"
    style: Literal["guided", "direct"] = "guided"
    include_approved_notes: bool = False


class Overrides(Strict):
    track: str | None = Field(default=None, max_length=100)
    subjects: list[Short] | None = Field(default=None, max_length=8)
    language: Literal["ar", "fr", "en"] | None = None
    detail: Literal["brief", "balanced", "deep"] | None = None
    style: Literal["guided", "direct"] | None = None
    include_approved_notes: bool | None = None


class Note(Strict):
    category: Literal["weakness", "mistake", "mastered", "goal"]
    content: str = Field(min_length=1, max_length=1000)


class AgentNote(Note):
    id: str | None = Field(default=None, max_length=100)
    evidence_message_id: str | None = Field(default=None, max_length=100)
    evidence_quote: str | None = Field(default=None, min_length=8, max_length=400)


class NoteId(Strict):
    id: str = Field(min_length=1, max_length=100)


class SourceImage(Strict):
    asset_id: str = Field(min_length=1, max_length=200)


class NoteDecision(Note):
    consent: bool = False


class PrivatePage(Strict):
    upload_id: str = Field(min_length=1, max_length=100)
    page: int = Field(default=1, ge=1, le=20)


class Criterion(Strict):
    title: str = Field(min_length=1, max_length=200)
    maximum: float = Field(gt=0, le=100)
    awarded: float | None = Field(default=None, ge=0, le=100)
    feedback: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def marks(self):
        if self.awarded is not None and self.awarded > self.maximum:
            raise ValueError("Awarded marks exceed maximum")
        return self


class Material(Strict):
    kind: Literal[
        "lesson_plan",
        "exercise_set",
        "exam",
        "grading",
        "reference_review",
    ]
    title: str = Field(min_length=1, max_length=150)
    answer: Answer
    rubric: list[Criterion] = Field(default_factory=list, max_length=30)
    total: float | None = Field(default=None, gt=0, le=100)
    solution: str = Field(default="", max_length=10000)

    @model_validator(mode="after")
    def complete(self):
        if self.kind == "exam" and (not self.rubric or not self.solution):
            raise ValueError("Generated tests require a rubric and a separate solution")
        if self.kind == "grading" and (
            not self.rubric or any(c.awarded is None for c in self.rubric)
        ):
            raise ValueError("Grading requires awarded marks and a rubric")
        if self.rubric and (
            self.total is None
            or abs(sum(c.maximum for c in self.rubric) - self.total) > 0.00001
        ):
            raise ValueError("Rubric marks must sum to the total")
        return self


class AccountLimits(Strict):
    role: Literal["owner", "student", "teacher"] | None = None
    active: bool | None = None
    daily_limit: int | None = Field(default=None, ge=0, le=10000)
    daily_tokens: int | None = Field(default=None, ge=0, le=10000000)
    messages_per_minute: int | None = Field(default=None, ge=1, le=60)
    max_active_runs: int | None = Field(default=None, ge=1, le=4)
    budget_alert: float | None = Field(default=None, ge=0, le=100000)
