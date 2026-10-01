# مصادر المراجعة والتراخيص

المراجعة التالية فحص مستودع وترخيص وعينات كود بتاريخ 2026-09-30، **ليست تدقيقًا أمنيًا أو اعتمادًا لجودة المشروع كاملة**.

| المشروع | ما فُحص | القرار |
|---|---|---|
| [OpenCode](https://github.com/anomalyco/opencode) | MIT، نشاط مستودع و`packages/opencode/src/session/retry.ts` عند `0112a92c416f5ad833d96e7a8308441f0a875d94` | استلهام bounded retry وRetry-After من القراءة؛ لا dependency ولا نسخ كود جديد |
| [OpenAI Agents Python](https://github.com/openai/openai-agents-python) | MIT و`src/agents/stream_events.py` عند `28e9f4fca26dd1c7e679398b87182868ecfad714` | فصل أحداث النص والأدوات الفعلية؛ agent core صغير مستقل، لا SDK dependency |
| [Claude Code](https://github.com/anthropics/claude-code) | `LICENSE.md` عند `6160717d8994f236ab381cf534fc1cde5347c12f`؛ all rights reserved/تجاري | لم يُنسخ أي كود |
| BookForge الموجود محليًا | MIT و32 اختبارًا baseline؛ ملفات المصدر محفوظة hashes في manifest | vendor namespace مع إبقاء الترخيص وإعادة استخدام queue/extraction/crops/Markdown/structure |

المكتبات المباشرة الأخرى: FastAPI (MIT)، Uvicorn (BSD-3-Clause)، HTTPX (BSD-3-Clause)، Pydantic (MIT)، Pillow (HPND)، Cryptography (Apache-2.0/BSD)، PyYAML (MIT)، React (MIT)، Vite (MIT)، TypeScript (Apache-2.0)، react-markdown/remark-math/rehype-katex (MIT)، KaTeX (MIT)، Playwright (Apache-2.0)، Noto Sans Arabic (OFL).

**PyMuPDF: AGPL-3.0 أو ترخيص تجاري.** قائمة أسماء تراخيص ليست legal opinion. راجع dependency versions وتراخيص transitive deps قبل الإطلاق أو إعادة التوزيع. `constraints.txt` و`package-lock.json` يثبتان نسخ الاختبار؛ يجب تحديثهما بشكل مدروس مع إعادة الاختبارات.
