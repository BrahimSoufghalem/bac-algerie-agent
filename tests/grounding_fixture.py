"""Known bilingual source/PDF fixtures; no OCR benchmark or official curriculum."""

import pymupdf
from bac.core.auth import create_user
from bac.core.db import uid
from bac.library.service import Library
from bac.vendor.bookforge.models.page import PageDocument
from tests.test_library import process_and_publish

TOPICS = {
    "projectile": (
        "حركة قذف بسرعة ابتدائية غير شاقولية",
        "القذف حركة المقذوفات: السرعة والتسارع، حركة القذف غير الشاقولية. "
        "Neglect air resistance; g is constant. Horizontal acceleration is zero; "
        "vertical acceleration is -g. Initial components: v0x=v0*cos(alpha), "
        "v0y=v0*sin(alpha). At time t: vx=v0x, vy=v0y-g*t. At the highest point "
        "vy=0 but vx generally stays nonzero. Velocity depends on time; acceleration "
        "is the rate of change of velocity. For plots use separate axes and units "
        "for velocity (m/s) and acceleration (m/s^2). With initial height zero: "
        "x=v0x*t, y=v0y*t-g*t^2/2. Numeric example values are illustrative, not "
        "data imposed by this reference. This is a controlled test source, not an official syllabus.",
    ),
    "arithmetic": (
        "حساب الجمع / Arithmetic",
        "To add two and three combine the quantities: 2+3=5. To solve x+1=2, "
        "subtract one from both sides and obtain x=1. Tests need a separate solution "
        "and rubric. These exercises are synthetic local inputs, not official questions.",
    ),
}


async def publish_reference(s, topic="projectile"):
    title, text = TOPICS[topic]
    user = create_user(
        s.db,
        topic + "@fixture.invalid",
        "Synthetic-password-1",
        "Synthetic source owner",
        "owner",
    )
    pdf = s.store.path(uid("fixture") + ".pdf")
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=850)
        page.insert_htmlbox(
            pymupdf.Rect(30, 30, 570, 820), f'<h2 dir="rtl">{title}</h2><p>{text}</p>'
        )
        doc.save(pdf)
    lib = Library(s)
    uploaded = lib.upload(
        pdf,
        topic + ".pdf",
        {
            "title": title,
            "kind": "book",
            "subject": "physics" if topic == "projectile" else "mathematics",
            "track": "science",
        },
        user,
    )
    original_factory = s.extraction_engine.provider_factory
    original_process = s.extraction_engine.process

    class Vision:
        async def extract(self, image, page, width, height):
            return PageDocument(
                pdf_page=page,
                width=width,
                height=height,
                languages=["ar", "en"],
                elements=[
                    {
                        "id": "lesson",
                        "type": "heading",
                        "order": 0,
                        "structure_type": "lesson",
                        "text": title,
                    },
                    {"id": "paragraph", "type": "paragraph", "order": 1, "text": text},
                ],
            ), {"total_tokens": 0}

    async def process(job):
        s.extraction_engine.provider_factory = lambda cfg, key: Vision()
        return await original_process(job)

    # Existing reviewed/published pipeline, but known transcription instead of paid Vision.
    s.extraction_engine.process = process
    try:
        document = await process_and_publish(s, lib, uploaded, user)
    finally:
        s.extraction_engine.process = original_process
        s.extraction_engine.provider_factory = original_factory
    return lib.nodes(document["id"], "lesson")[0]["id"]
