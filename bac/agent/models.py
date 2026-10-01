from typing import Literal, Annotated
from pydantic import BaseModel, Field, ConfigDict, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextBlock(Strict):
    type: Literal["text"] = "text"
    text: str = Field(max_length=24000)


class EquationBlock(Strict):
    type: Literal["equation"] = "equation"
    latex: str = Field(max_length=4000)


class ImageBlock(Strict):
    type: Literal["image"] = "image"
    asset_id: str = Field(max_length=200)
    caption: str = Field(default="", max_length=2000)


class TableBlock(Strict):
    type: Literal["table"] = "table"
    headers: list[str] = Field(max_length=20)
    rows: list[list[str]] = Field(max_length=100)

    @model_validator(mode="after")
    def safe_shape(self):
        if not self.headers or any(len(row) != len(self.headers) for row in self.rows):
            raise ValueError("Table columns must match the headers")
        if any(
            len(cell) > 4000
            for cell in self.headers + [cell for row in self.rows for cell in row]
        ):
            raise ValueError("Table cell is too large")
        return self


class CodeBlock(Strict):
    type: Literal["code"] = "code"
    language: str = Field(default="python", max_length=30)
    text: str = Field(max_length=12000)


Block = Annotated[
    TextBlock | EquationBlock | ImageBlock | TableBlock | CodeBlock,
    Field(discriminator="type"),
]


class Answer(Strict):
    blocks: list[Block] = Field(min_length=1, max_length=30)
    source_ids: list[str] = Field(default_factory=list, max_length=30)
    warnings: list[str] = Field(default_factory=list, max_length=20)


class ModelConfig(Strict):
    base_url: str = Field(min_length=1, max_length=2048)
    model: str = Field(min_length=1, max_length=200)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=4000, ge=500, le=32000)
    timeout: int = Field(default=90, ge=5, le=180)
    input_price_per_million: float | None = Field(default=None, ge=0)
    output_price_per_million: float | None = Field(default=None, ge=0)
    cached_price_per_million: float | None = Field(default=None, ge=0)
    output_mode: Literal["json_object", "json_schema", "none"] = "json_object"
