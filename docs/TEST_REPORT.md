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

# تقرير المرحلة الثانية

## دليل محلي بعد استعادة بيئة التنفيذ

- Backend: **40 passed**، مع تحذير deprecation واحد من Starlette TestClient.
- Ruff F: **All checks passed**، الكود الجديد والاختبارات، دون تعديل vendor.
- TypeScript strict + Vite production build: نجح.
- Playwright: **3 passed**؛ كتاب ودروس، امتحان/حل بنطاقين ومصادر ملفين، وسلسلة كاملة بلا حل. اختبارات سطح المكتب و390px والـCSS/صور المصدر/KaTeX/source modal/CSRF/RBAC وSSE تعمل فعلًا.
- SHA-256 لكل الملفات في `bookforge-reuse.json`: لا اختلاف، بما يشمل fixture generator. نتيجة baseline BookForge الأصلية السابقة 32 passed؛ لم يُعَد ادعاء تشغيله في البيئة المستعادة.
- طلبات مدفوعة جديدة: **0**. كل vision/chat fixture صريح داخل tests فقط.
- GitHub CI: يُفحص منفصلًا في PR قبل الدمج، لا يُستنتج من نجاح محلي.

### الاختبارات المضافة

1. الموضوع والحل المنفصلان يُحفظان PDF/JSON/rasters/crops مستقلين؛ تحافظ source IDs على role/file/page.
2. ملف مدمج، نطاقات غير متداخلة؛ enqueue مرة واحدة لكل raw PDF. كل نص في نطاقه الصحيح.
3. اختلاف مادة/تخصص/سنة/دورة/نوع امتحان يرفض التحقق. لا اعتماد قبل تأكيد المصدر والمطابقة.
4. تغيير الهوية أو النطاق يبطل التأكيد؛ تعديل نسخة منشورة يرفض. مسودة جديدة لا تغيّر metadata المنشور.
5. امتحان/سلسلة/مرجع عقدة واحدة، بلا invented lessons أو individual exercise nodes.
6. missing solution صريح؛ الحزمة الزائدة ترفض كليًا ولا تمنح مصدرًا مقروءًا وهميًا.
7. درس طويل أجزاء ثابتة عند عناصر كاملة، citation للجزء فقط؛ درس واحد في صفحة مشتركة لا يستدعي عناصر الدرس الآخر.
8. metadata-only بلا قراءة ملفات؛ cache مشترك بين أدوات/Library instances ويظل publication-scoped.
9. JSON الناتج كاملًا يخضع للحد، لا content وحده؛ source لم يدخل context restore لا يمنح citation credit.
10. تعديل raw Markdown/JSON بعد النشر لا يغير قراءة الطالب أو معاينة المالك للنسخة المعتمدة.
11. migration فعلية من schema v1، backfill الهوية، legacy parts من approved Markdown فقط؛ الأرشفة تمنع القراءة حتى مع cache.
12. صفحة فاشلة تبقى بعلامة gap صريحة و`extraction_complete=false`، والأصل يبقى محفوظًا.

## المراجعة البصرية: قيد صريح

تم توليد صور مراجعة للحاسوب/الهاتف للمراجعة والحل والفلاتر وغياب الحل، وتؤكد اختبارات المتصفح عدم horizontal overflow. بعد إعادة تشغيل بيئة التنفيذ لم يعد `/skills` المجمّع متاحًا، فاستُخدم renderer محلي عبر Playwright. **تعطّلت أداة view_image/download نفسها (computer_helper_failed)**؛ لا نعتبر توليد الصور أو نجاح الاختبارات بديلًا عن النظر فيها، ولا ندّعي نجاح مراجعة بصرية جديدة للمرحلة الثانية. يلزم استكمالها قبل القبول النهائي للإنتاج. صور الاختبارات لا تحتوي أسرارًا أو بيانات كتب حقيقية ولا تدخل Git.

## حدود المرحلة

التحقق من المطابقة owner attestation مع هوية ودليل، وليس شهادة مستقلة بصحة الحل العلمي/رسمية المصدر. لا paid real-model benchmark ولا Docker build ولا load/security audit شامل في هذه الجولة. أجزاء legacy تحافظ على بلوكات Markdown، وsnapshot v1 لا يصبح له JSON frozen مختلق. جميع حدود tool/context بالحروف، وجمع token usage الفعلي/أسعار provider مستقل عن cache الملفات. راجع `RETRIEVAL.md` والمرحلتين 3–5.
