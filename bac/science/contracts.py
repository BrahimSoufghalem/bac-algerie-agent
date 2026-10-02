"""Bounded contracts. Expressions are an AST grammar, never Python eval."""

from typing import Literal
from pydantic import Field, model_validator
from bac.agent.models import Strict


class Expression(Strict):
    expression: str = Field(min_length=1, max_length=500)
    values: dict[str, str] = Field(default_factory=dict, max_length=20)


class Calculate(Expression):
    pass


class VerifyCalculation(Expression):
    expected: str = Field(min_length=1, max_length=500)
    absolute_tolerance: float = Field(default=1e-9, ge=0, le=0.01, allow_inf_nan=False)
    relative_tolerance: float = Field(default=1e-9, ge=0, le=0.01, allow_inf_nan=False)


class Condition(Strict):
    lhs: str = Field(min_length=1, max_length=300)
    relation: Literal["eq", "ne", "lt", "le", "gt", "ge"]
    rhs: str = Field(default="0", min_length=1, max_length=300)


class VerifyEquation(Strict):
    lhs: str = Field(min_length=1, max_length=500)
    rhs: str = Field(min_length=1, max_length=500)
    values: dict[str, str] = Field(default_factory=dict, max_length=20)
    conditions: list[Condition] = Field(default_factory=list, max_length=12)
    absolute_tolerance: float = Field(default=1e-9, ge=0, le=0.01, allow_inf_nan=False)
    relative_tolerance: float = Field(default=1e-9, ge=0, le=0.01, allow_inf_nan=False)


class Symbolic(Strict):
    operation: Literal["simplify", "differentiate", "integrate", "solve", "compare"]
    expression: str = Field(min_length=1, max_length=500)
    other: str = Field(default="0", min_length=1, max_length=500)
    variable: str = Field(default="x", min_length=1, max_length=32)
    positive_symbols: list[str] = Field(default_factory=list, max_length=10)


class ConvertUnit(Strict):
    value: str = Field(min_length=1, max_length=100)
    from_unit: str = Field(min_length=1, max_length=100)
    to_unit: str = Field(min_length=1, max_length=100)


class VerifyDimensions(Strict):
    lhs: str = Field(min_length=1, max_length=500)
    rhs: str = Field(min_length=1, max_length=500)
    units: dict[str, str] = Field(min_length=1, max_length=20)


class ScientificCode(Strict):
    code: str = Field(min_length=1, max_length=6000)
    inputs: dict[str, float | list[float]] = Field(default_factory=dict, max_length=12)


class Series(Strict):
    label: str = Field(min_length=1, max_length=80)
    x: list[float] = Field(min_length=2, max_length=401)
    y: list[float | None] = Field(min_length=2, max_length=401)

    @model_validator(mode="after")
    def shape(self):
        if len(self.x) != len(self.y):
            raise ValueError("x/y lengths differ")
        return self


class Plot(Strict):
    title: str = Field(min_length=1, max_length=150)
    x_label: str = Field(min_length=1, max_length=100)
    y_label: str = Field(min_length=1, max_length=100)
    kind: Literal["line", "scatter", "bar"] = "line"
    series: list[Series] = Field(min_length=1, max_length=4)


class PlotFunction(Strict):
    expression: str = Field(min_length=1, max_length=500)
    variable: str = Field(default="x", min_length=1, max_length=32)
    values: dict[str, str] = Field(default_factory=dict, max_length=20)
    lower: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    upper: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    samples: int = Field(default=101, ge=21, le=201)
    title: str = Field(min_length=1, max_length=150)
    x_label: str = Field(default="x", min_length=1, max_length=100)
    y_label: str = Field(default="f(x)", min_length=1, max_length=100)

    @model_validator(mode="after")
    def interval(self):
        if self.lower >= self.upper:
            raise ValueError("lower must be smaller than upper")
        return self


class PlotFromResult(Strict):
    result_id: str = Field(min_length=1, max_length=100)
    x_output: str = Field(min_length=1, max_length=64)
    y_output: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=150)
    x_label: str = Field(min_length=1, max_length=100)
    y_label: str = Field(min_length=1, max_length=100)
    kind: Literal["line", "scatter", "bar"] = "line"


class DiagramElement(Strict):
    kind: Literal["segment", "vector", "circle", "point"]
    x: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    y: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    x2: float | None = Field(default=None, allow_inf_nan=False, ge=-1e6, le=1e6)
    y2: float | None = Field(default=None, allow_inf_nan=False, ge=-1e6, le=1e6)
    radius: float | None = Field(default=None, allow_inf_nan=False, gt=0, le=1e6)
    label: str = Field(default="", max_length=80)


class Diagram(Strict):
    title: str = Field(min_length=1, max_length=150)
    x_label: str = Field(default="x", min_length=1, max_length=100)
    y_label: str = Field(default="y", min_length=1, max_length=100)
    x_min: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    x_max: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    y_min: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    y_max: float = Field(allow_inf_nan=False, ge=-1e6, le=1e6)
    elements: list[DiagramElement] = Field(min_length=1, max_length=30)

    @model_validator(mode="after")
    def geometry(self):
        if self.x_max - self.x_min < 1e-6 or self.y_max - self.y_min < 1e-6:
            raise ValueError("Diagram requires non-empty coordinate bounds")
        for e in self.elements:
            if (
                not self.x_min <= e.x <= self.x_max
                or not self.y_min <= e.y <= self.y_max
            ):
                raise ValueError("Diagram geometry outside bounds")
            if e.kind in ("segment", "vector"):
                if (
                    e.x2 is None
                    or e.y2 is None
                    or not self.x_min <= e.x2 <= self.x_max
                    or not self.y_min <= e.y2 <= self.y_max
                ):
                    raise ValueError("A line/vector requires bounded x2/y2")
                if e.radius is not None or (e.x == e.x2 and e.y == e.y2):
                    raise ValueError("Line/vector must have length and no radius")
            elif e.x2 is not None or e.y2 is not None:
                raise ValueError("Only line/vector can have endpoints")
            if e.kind == "circle":
                if e.radius is None or not (
                    self.x_min <= e.x - e.radius
                    and e.x + e.radius <= self.x_max
                    and self.y_min <= e.y - e.radius
                    and e.y + e.radius <= self.y_max
                ):
                    raise ValueError("Circle radius must be inside bounds")
            elif e.radius is not None:
                raise ValueError("Only circle can have radius")
        return self
