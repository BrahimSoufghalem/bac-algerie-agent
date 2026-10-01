from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Cell(StrictModel):
    row: int = Field(ge=0)
    column: int = Field(ge=0)
    row_span: int = Field(default=1, ge=1)
    column_span: int = Field(default=1, ge=1)
    text: str


class TocEntry(StrictModel):
    title: str
    number: str | None = None
    printed_page: str | None = None
    level: int = Field(default=1, ge=1, le=12)
    kind: Literal['part', 'chapter', 'unit', 'module', 'lesson', 'section', 'appendix', 'unknown'] = 'unknown'


class Reference(StrictModel):
    target_text: str
    relation: Literal['references', 'prerequisite'] = 'references'
    evidence: str


class Element(StrictModel):
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    type: Literal['heading', 'paragraph', 'list', 'figure', 'image', 'diagram', 'table', 'equation', 'caption', 'footnote', 'header', 'footer', 'page_number', 'toc', 'unknown']
    order: int = Field(ge=0)
    bbox: list[float] | None = None
    text: str = ''
    level: int = Field(default=1, ge=1, le=12)
    structure_type: Literal['part', 'chapter', 'unit', 'module', 'lesson', 'section', 'front_matter', 'toc', 'appendix', 'index', 'bibliography', 'unknown'] = 'unknown'
    label: str | None = None
    caption: str = ''
    parent_element_id: str | None = None
    latex: str = ''
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    cells: list[Cell] = Field(default_factory=list)
    footnotes: list[str] = Field(default_factory=list)
    complex_table: bool = False
    toc_entries: list[TocEntry] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)
    unreadable: bool = False


class PageDocument(StrictModel):
    schema_version: str = '1.0'
    pdf_page: int = Field(ge=1)
    printed_page: str | None = None
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    coordinate_system: Literal['pixels'] = 'pixels'
    languages: list[str] = Field(default_factory=list)
    is_blank: bool = False
    reading_order_confidence: float | None = Field(default=None, ge=0, le=1)
    elements: list[Element] = Field(default_factory=list)
