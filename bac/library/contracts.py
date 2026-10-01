"""Owner-supplied source identity; no LLM guesses or official-solution invention."""

from typing import Literal
from pydantic import Field, model_validator
from bac.agent.models import Strict


class DocumentMetadata(Strict):
    title: str = Field(default="", max_length=200)
    kind: Literal["book", "exam", "exercise_collection", "reference"]
    subject: str = Field(min_length=1, max_length=100)
    track: str = Field(min_length=1, max_length=100)
    year: str | None = Field(default=None, max_length=20)
    source: str = Field(default="", max_length=2048)
    session: str | None = Field(default=None, max_length=100)
    exam_type: str | None = Field(default=None, max_length=100)
    institution: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def normalize(self):
        self.subject = self.subject.strip()
        self.track = self.track.strip()
        if not self.subject or not self.track:
            raise ValueError("Subject and track are required")
        self.year = self.year.strip() or None if self.year else None
        self.session = self.session.strip() or None if self.session else None
        return self


class SolutionMetadata(Strict):
    subject: str = Field(min_length=1, max_length=100)
    track: str = Field(min_length=1, max_length=100)
    year: str | None = Field(default=None, max_length=20)
    session: str | None = Field(default=None, max_length=100)
    exam_type: str | None = Field(default=None, max_length=100)
    source: str = Field(min_length=1, max_length=2048)
    designation: Literal["provided", "official_source"] = "provided"

    @model_validator(mode="after")
    def nonblank(self):
        for name in ("subject", "track", "source"):
            setattr(self, name, getattr(self, name).strip())
            if not getattr(self, name):
                raise ValueError("Solution identity and source cannot be blank")
        return self


class PageRange(Strict):
    first_page: int = Field(ge=1)
    last_page: int = Field(ge=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.last_page < self.first_page:
            raise ValueError("Invalid page range")
        return self


class SolutionVerification(Strict):
    matching_confirmed: bool
    source_confirmed: bool
    evidence: str = Field(min_length=20, max_length=4000)
