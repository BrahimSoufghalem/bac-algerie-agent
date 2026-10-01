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


class FixtureScience:
    """Exercises real scientific tools with an explicit no-network chat fixture."""

    def __init__(self):
        self.step = 0
        self.checks = []

    async def stream(self, messages, tools):
        self.step += 1
        if self.step == 1:
            question = next(
                m["content"] for m in reversed(messages) if m["role"] == "user"
            )
            self.kind = (
                "bar"
                if "أعمدة" in question
                else "scatter"
                if "نقاط" in question
                else "line"
            )
            tasks = [
                ("verify_calculation", {"expression": "2+2", "expected": "5"}),
                (
                    "verify_dimensions",
                    {
                        "lhs": "v*t+a*t**2/2",
                        "rhs": "d",
                        "units": {"v": "m/s", "t": "s", "a": "m/s**2", "d": "m"},
                    },
                ),
            ]
        elif self.step == 2:
            self.checks = [
                json.loads(x["content"])["result_id"]
                for x in messages
                if x["role"] == "tool"
            ]
            tasks = [
                (
                    "run_scientific_code",
                    {
                        "code": 'xs = linspace(0, 2, 21)\nys = []\nfor t in xs:\n    ys = ys + [v*t + a*t**2/2]\nemit("time", xs)\nemit("distance", ys)',
                        "inputs": {"v": 3, "a": 2},
                    },
                )
            ]
        elif self.step == 3:
            result = json.loads(messages[-1]["content"])
            tasks = [
                (
                    "plot_from_result",
                    {
                        "result_id": result["result_id"],
                        "x_output": "time",
                        "y_output": "distance",
                        "title": "الحركة تحت تسارع ثابت — بيانات اختبار",
                        "x_label": "time (s)",
                        "y_label": "distance (m)",
                        "kind": self.kind,
                    },
                )
            ]
            tasks.append(
                (
                    "draw_diagram",
                    {
                        "title": "مخطط متجه تعليمي — مثال مقيّد",
                        "x_min": -2,
                        "x_max": 2,
                        "y_min": -2,
                        "y_max": 2,
                        "elements": [
                            {"kind": "circle", "x": 0, "y": 0, "radius": 0.4},
                            {
                                "kind": "vector",
                                "x": 0,
                                "y": 0,
                                "x2": 1,
                                "y2": 1,
                                "label": "F = ma",
                            },
                        ],
                    },
                )
            )
        else:
            result = json.loads(messages[-2]["content"])
            diagram = json.loads(messages[-1]["content"])
            tasks = [
                (
                    "render_answer",
                    {
                        "blocks": [
                            {
                                "type": "text",
                                "text": "## حساب علمي بأدوات فعلية\n\nهذا اختبار محلي صريح دون نموذج خارجي. نبدأ بفحص نتيجة خاطئة، ثم نفحص الأبعاد ونحسب مسارًا.",
                            },
                            {"type": "verification", "result_id": self.checks[0]},
                            {
                                "type": "equation",
                                "latex": "d=vt+\\frac{1}{2}at^2",
                                "result_ids": [self.checks[1]],
                            },
                            {"type": "verification", "result_id": self.checks[1]},
                            {"type": "graph", "result_id": result["result_id"]},
                            {"type": "graph", "result_id": diagram["result_id"]},
                            {
                                "type": "text",
                                "text": "### تفسير بعد الرسم\n\nباستخدام v = 3 m/s وa = 2 m/s² نحصل عند t = 2 s على d = 10 m. الأبعاد متسقة، لكن ذلك لا يثبت أن هذه المعطيات تفسر مسألة أصلية بعينها.",
                            },
                        ]
                    },
                )
            ]
        yield {"type": "usage", "data": {"prompt_tokens": 0, "completion_tokens": 0}}
        yield {
            "type": "result",
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": f"science{self.step}_{i}",
                        "type": "function",
                        "function": {"name": name, "arguments": js(args)},
                    }
                    for i, (name, args) in enumerate(tasks)
                ],
            },
        }


class RoutedFixture:
    def __init__(self):
        self.delegate = None

    async def stream(self, messages, tools):
        if not self.delegate:
            question = next(
                m["content"] for m in reversed(messages) if m["role"] == "user"
            )
            self.delegate = FixtureScience() if "علمي" in question else FixtureChat()
        async for item in self.delegate.stream(messages, tools):
            yield item


s.chat_factory = lambda cfg, key: RoutedFixture()

# Preseed ONLY test users; do not relax production registration rate limits.
for mode in ("line", "bar", "scatter"):
    email = f"science-{mode}@test.invalid"
    if not s.db.one("SELECT 1 FROM users WHERE email=?", (email,)):
        create_user(s.db, email, "Test-science-password-1", "طالب الحساب العلمي")
