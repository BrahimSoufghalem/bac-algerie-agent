# تقرير المرحلة الأولى

## نتائج محلية فعلية

| الفحص | النتيجة |
|---|---|
| BookForge الأصلي قبل النسخ | 32 passed؛ المصدر الأصلي لم يتغير |
| اختبارات backend الجديدة | 19 passed؛ تحذير deprecation واحد من Starlette TestClient |
| Ruff: أخطاء الأسماء/الاستيرادات للكود الجديد والاختبارات | All checks passed |
| TypeScript strict + Vite production build | نجح، chunks الرئيسية أقل من 500 kB بعد الفصل |
| Playwright، مسار كامل من الواجهة | 1 passed، يشمل عدة أفعال وأذونات وreload وشاشات الهاتف |
| فحص بصري | دخول desktop/mobile، محادثة فارغة، جواب بمعادلة/صورة/جدول، review، source modal، فهرس وقائمة mobile، models، usage وإدارة المحتوى |
| طلبات Vision/تدريس مدفوعة جديدة | 0 |
| Docker build | لم يُنفَّذ؛ Docker غير موجود في بيئة التنفيذ |
| GitHub Actions | حالة منفصلة عن الاختبارات المحلية؛ تُراجع عبر check runs في PR |

## ما اختُبر

- تكرار migrations، رفض نسخة DB أحدث غير معروفة، scrypt والجلسات وحدود الطلبات المحفوظة.
- طالبان منفصلان، owner-only upload/model config، CSRF، رفض self-escalation، وعدم إعادة password في validation errors.
- Draft غير مرئي، لا نشر قبل مراجعة؛ snapshot ثابت رغم تغيير ملف الاستخراج الخام؛ الأرشفة تمنع search/node/image حتى بعد تحميل المصدر.
- claim متزامن من ثمانية threads: وظيفة واحدة فقط؛ fencing يمنع worker قديم؛ run مدفوع منقطع يُعلَّم INTERRUPTED ولا يعاد تلقائيًا.
- تنفيذ أداة lesson حقيقية إلى مكتبة منشورة، source_ids محمّلة فقط، validation للصورة والجدول وحدود JSON، bounded loop/step failure دون جواب نجاح وهمي.
- إيقاف async أثناء الطلب، retry يعيد السؤال نفسه بلا تكراره ويحفظ الرد السابق كنسخة غير نشطة.
- تحليل SSE الحقيقي عبر HTTPX MockTransport: تجميع tool argument fragments، usage/cache الفعلي، تجاهل reasoning_content، رفض truncation، عدم تكرار HTTP 429/503 خفيًا.
- Playwright: رفع PDF scanned اصطناعي من خمس صفحات → render → structured fixture JSON → crops/Markdown/هيكل → review مع الإقرار بالصفحة المتعمدة منخفضة الجودة → publish → تسجيل طالب → search_library → get_lesson_full → streamed answer وsources → صورة/KaTeX/table → reload → source modal → فهرس الهاتف → فتح/إغلاق القائمة → عرض جدول الاستخدام.

## حدود الدليل

كل موديل في الاختبارات mock صريح داخل tests فقط. يتشغّل parser وpipeline وDB وworker وAPI والمتصفح فعلًا، لكن لا تُثبت الاختبارات دقة Vision على كتاب حقيقي أو correctness علمي أو توافق أدوات LUNA. المصدر الاصطناعي ليس كتابًا رسميًا ولا benchmark OCR. الأرقام 0 tokens في browser fixture هي بيانات اختبار، وليست billing لمزوّد خارجي. لا يوجد ادعاء load test أو security audit كامل أو جاهزية production لجميع المراحل.

## إعادة الفحص

```bash
pip install -r requirements-dev.txt -c constraints.txt
pytest -q
ruff check bac/core bac/agent bac/api bac/library bac/worker.py bac/cli.py tests --select F
npm ci
npm run build
npx playwright install chromium
npm run test:browser
```
