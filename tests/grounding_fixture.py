"""Known synthetic Markdown references; never an official-curriculum benchmark."""

import yaml
from bac.core.auth import create_user
from bac.core.db import uid
from bac.library.service import Library

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
    owner = create_user(
        s.db,
        topic + "@fixture.invalid",
        "Synthetic-password-1",
        "Synthetic source owner",
        "owner",
    )
    path = s.store.path(uid("fixture") + ".md")
    metadata = {
        "section_id": "1",
        "title": title,
        "summary": "شرح للمفهوم وشروطه وعلاقاته وأمثلة حسابية؛ " + title,
        "covers": [title],
    }
    path.write_text(
        "## [صفحة الكتاب 1 / صفحة PDF 1]\n# "
        + title
        + "\n\n"
        + text
        + "\n\n```yaml\n"
        + yaml.safe_dump(metadata, allow_unicode=True)
        + "```\n"
    )
    lib = Library(s)
    result = lib.upload(
        path,
        topic + ".md",
        {
            "title": title,
            "kind": "book",
            "subject": "physics" if topic == "projectile" else "mathematics",
            "track": "science",
        },
        owner,
    )
    lib.review(result["version_id"], owner, True, "Synthetic source reviewed")
    doc = lib.publish(result["version_id"], owner)
    return lib.nodes(doc["id"], "lesson")[0]["id"]
