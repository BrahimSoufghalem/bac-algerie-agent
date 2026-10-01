"""Explicit offline-only browser test server. Never a production entry point."""

import asyncio, json, os, time
from contextlib import asynccontextmanager
from pathlib import Path

root = Path(os.environ.get("TEST_DATA_DIR", "/tmp/masar-browser-test")).resolve()
os.environ["DATA_DIR"] = str(root)
from bac.api.main import create_app
from bac.core.services import Services
from bac.core.auth import create_user
from bac.core.db import js, uid
from bac.agent.engine import AgentEngine
from bac.vendor.bookforge.models.page import PageDocument
from tests.fixture_book import golden_page


class FixtureVision:
    async def extract(self, image, page, width, height):
        await asyncio.sleep(0.1)
        return PageDocument.model_validate(golden_page(page, width, height)), {
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }


class FixtureChat:
    def __init__(self):
        self.step = 0

    async def stream(self, messages, tools):
        self.step += 1
        await asyncio.sleep(0.15)
        if self.step == 1:
            question = next(
                m["content"] for m in reversed(messages) if m["role"] == "user"
            )
            self.mode = (
                "exam"
                if "امتحان" in question
                else "exercise_collection"
                if "سلسلة" in question
                else "lesson"
            )
            name, args = (
                "search_library",
                {
                    "query": "الحرارة",
                    **({"kind": self.mode} if self.mode != "lesson" else {}),
                },
            )
        elif self.step == 2:
            hits = json.loads(messages[-1]["content"])["items"]
            hit = next(x for x in hits if x["kind"] == self.mode)
            name, args = (
                {
                    "lesson": "get_lesson_full",
                    "exam": "get_exam_with_solution",
                    "exercise_collection": "get_exercise_collection",
                }[self.mode],
                {"node_id": hit["node_id"]},
            )
        else:
            result = json.loads(messages[-1]["content"])
            node = result["node"]["id"]
            figure = next(a for a in result["assets"] if a["type"] == "figure")
            yield {"type": "delta", "text": "قرأت المصدر المنشور. "}
            name, args = (
                "render_answer",
                {
                    "blocks": [
                        {
                            "type": "text",
                            "text": "## الحرارة وانتقال الطاقة\n\nوفق الدرس المنشور، الحرارة **طاقة تنتقل من الجسم الساخن إلى الجسم البارد**. درجة الحرارة تقاس بوحدة كلفن.\n\nهذه إجابة اختبار محلي بمزوّد وهمي صريح؛ لم يُستخدم نموذج خارجي.",
                        },
                        {"type": "equation", "latex": "PV=nRT"},
                        {
                            "type": "image",
                            "asset_id": figure["id"],
                            "caption": "صورة مقصوصة من صفحة المصدر الأصلية؛ وليست صورة مولدة.",
                        },
                        {
                            "type": "table",
                            "headers": ["الكمية", "القيمة كما في المصدر"],
                            "rows": [["Temperature", "25 °C"], ["Pressure", "1.2 MPa"]],
                        },
                    ],
                    "source_ids": [x.get("source_id", node) for x in result["sources"]],
                },
            )
        if self.step == 3 and self.mode != "lesson":
            args["blocks"][0]["text"] = (
                "## الحزمة الكاملة من المصدر\n\nاستدعيت الموضوع كاملًا مع الحل المطابق إن وُجد. هذا اختبار محلي، وليس حلًا رسميًا مولّدًا."
            )
        yield {"type": "usage", "data": {"prompt_tokens": 0, "completion_tokens": 0}}
        yield {
            "type": "result",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "fixture" + str(self.step),
                        "type": "function",
                        "function": {"name": name, "arguments": js(args)},
                    }
                ],
            },
        }


s = Services(
    vision_factory=lambda cfg, key: FixtureVision(),
    chat_factory=lambda cfg, key: FixtureChat(),
)
if not s.db.one("SELECT 1 FROM users WHERE role='owner'"):
    create_user(
        s.db, "owner@test.invalid", "Test-password-only-1", "المالك التجريبي", "owner"
    )
for slot in ["agent", "extraction"]:
    if not s.db.one("SELECT 1 FROM active_models WHERE slot=?", (slot,)):
        id = uid("cfg")
        s.db.execute(
            "INSERT INTO model_configs VALUES(?,?,?,?,?)",
            (
                id,
                slot,
                js(
                    {
                        "base_url": "https://example.org/v1",
                        "model": "offline-test-fixture",
                    }
                ),
                s.vault.encrypt("offline-test-key"),
                time.time(),
            ),
        )
        s.db.execute("INSERT INTO active_models VALUES(?,?)", (slot, id))
app = create_app(s)


@asynccontextmanager
async def lifespan(app):
    engine = AgentEngine(s)
    tasks = [
        asyncio.create_task(engine.run()),
        asyncio.create_task(s.extraction_engine.run()),
    ]
    try:
        yield
    finally:
        engine.stop.set()
        s.extraction_engine.stopping.set()
        await asyncio.gather(*tasks)


app.router.lifespan_context = lifespan
