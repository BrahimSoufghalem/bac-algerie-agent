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

# تقرير المرحلة الثالثة

- Baseline قبل المرحلة: **40 passed**. الاختبارات النهائية للخلفية: **75 passed**، مع تحذير Starlette TestClient deprecation واحد. منها 35 scientific cases باحتساب parameterization.
- Ruff F checks على app/tests الجديدة مع استثناء vendor القديم: نجح. TypeScript strict + Vite build: نجح.
- Playwright: **6 passed**، الثلاثة السابقة وثلاثة مسارات علمية line/bar/scatter مع failed+passed evidence/real-code arrays/interactive chart/diagram/reload/390px. حسابات science مُحضّرة داخل test server فقط، لأن الستة تجاوزت registration rate cap الحقيقي؛ لم تُخفَّض حماية الإنتاج. GitHub CI يُراجع مستقلًا قبل الدمج.
- اختبارات denominator cancellation، missing values/constraints، real/positive assumptions ومجالات symbolic، 50digits/tolerances، SI/affine/delta temperatures، shape/finite/domain/chart/source scope.
- رفض imports/attributes/files/network/while/comprehensions/huge allocations، unreachable unsafe calls، loop/step caps. اختبارات حقيقية لقتل child بالdeadline ولرفض address-space منخفض، مع semaphore recovery؛ لا mocks للعزل.
- أصالة result_id ورفض payload من النموذج/ID من run آخر، graph-from-real-arrays، failure autoinclusion، full-wrapper output budget، cancellation، privacy/unauthenticated/another-student denial، integrity mismatch، cascade delete، DB migrations، actual agent events/SSE replay+saved blocks.
- لا paid Vision/teaching requests جديدة. جميع chat/vision fixtures صريحة؛ العمليات العلمية نفسها حقيقية. hashes BookForge/vendor تبقى كما هي؛ لا إعادة ادعاء تشغيل baseline BookForge32 في البيئة الحالية.

## قيود الدليل

الـCPU/ذاكرة/wall caps وAST boundary ليست VM أو seccomp/OS-security audit. child يعمل بهوية الخدمة ويحمّل مكتبات التطبيق الموثوقة؛ generated program لا يملك filesystem/network/shell APIs. الاختبارات لا تثبت correctness علمي شامل أو تفسير السؤال أو توافق أدوات LUNA الواقعي. Docker/load/native dependency security وscoped service tokens/المراحل4–5 ليست منجزة.

تم التقاط PNG فعلية للرسم في desktop/mobile؛ **فشلت أداة view_image ثانية بـcomputer_helper_failed**. لا ندّعي مراجعة بصرية للمرحلة الثالثة، ويلزم استكمال visual QA للمرحلتين2–3 قبل القبول النهائي. ملفات SKILL/capture المجمّعة غير متاحة في البيئة المستعادة؛ Playwright فقط للوظائف والتقاط الصور.

# تقرير المرحلة الرابعة

## الدليل المحلي النهائي

- Backend: **99 passed** (75 baseline + 24 learning/privacy/controls parameterized cases), Starlette TestClient deprecation warning only. Ruff F على app/tests الجديدة، strict TypeScript + Vite build، وpip check نجحت.
- Playwright: **10 passed**: ستة مسارات الكتاب/الحزم/الحسابات العلمية السابقة، وأربعة لمسارات الطالب الخاص/الأستاذ/التدريب الذاتي/المالك. اختبارات desktop/390px، لا horizontal overflow، تحميل فعلي لصورة خاصة، pending note ثم مراجعة/تعديل/موافقة، حذف/تصدير، same-engine draft tool + rubric/solution + reload، إنشاء أستاذ وحد 0 والأسعار وإشعار الحفظ. نتيجة المجموعة النهائية 45.1 ثانية في البيئة المحلية؛ ليست load benchmark.
- اختبار الاتصال الحقيقي بالشبكة **لم يُجرَ**: HTTPX MockTransport يثبت GET /models فقط بعد confirm صريح، وعدم كشف المفتاح، ولا أي generation requests. Save/navigation/upload لا يرسلون توليدًا مدفوعًا.
- Wrapper لقياس Vision عند الطلب الفعلي يحافظ على provider/config snapshot؛ reads/cache لا يُحتسبان requests. Cache المفقود والـtokens/cost المفقودة ليست أصفارًا. حساب التكلفة ورفض token-budget عند missing usage، قبل أول طلب وقبل الطلب التالي، اختُبرا.
- حسابات مختلفة وأستاذ ومالك لا يستطيعون قراءة private chat files/notes/drafts؛ CSRF/no-store ورفض MIME/HTML/SVG/oversize/extra keys وexpiry/delete/Filesystem cleanup/JSON export/account erasure بعد completed run اختُبرت.
- المصدر/التوقيت للملاحظة من run الحقيقي، source deactivated يمنع approval؛ notes opt-in false، typed overrides، stable role/system prefix، context snapshots، إلغاء active run عند تعديل/حذف، ومسح نسخ note من persisted snapshots.
- أدوات الأنماط الستة تعمل عبر نفس المحرك؛ student فقط self_practice، grading awarded≤maximum وrubric sums، test solution منفصل، generated draft دائمًا غير رسمي. كثرة/قدرة النصوص التي ينتجها مزوّد فعلي ليست مثبتة بهذه fixtures.
- Transactions تمنع concurrent allowance races، migrations serialized على Linux عند startup متعدد؛ last active owner لا يُحذف، role change يلغى sessions/runs، 0 allowance يعمل، سجل الإدارة بلا keys/passwords.
- BookForge reuse manifest: **26 files، 0 hash mismatches**. لا تغيير vendor أو المشروع الأصلي؛ لا PDF/data/secrets committed. جميع chat/vision fixtures صريحة في tests فقط. **0 paid API calls** في هذه المرحلة.

## ما لم يثبت بعد

حُفظت HTML previews ثم ست لقطات PNG فعلية لتفضيلات desktop/mobile وملاحظات/مسودة/حسابات/أسعار. **المراجعة البصرية الفعلية ما زالت معلقة** مع المراحل 2–3؛ اختبارات DOM/CSS وعدم overflow ليست بديلًا عن النظر إلى الصور. لا claim visual approval.

Phase 5 ما زالت مفتوحة: provider capability/educational quality (including real LUNA tool/vision compatibility), full security/native-parser audit, hostile uploads/resource/storage/orphan cleanup, load tests, actual backup/restore, scoped service tokens, email/password lifecycle, Docker deployment and final acceptance. Private-file expiry denies access immediately but deletion requires running services; data already in chat/provider isn't recalled. Account token/run caps apply to teaching, not a global BookForge/provider invoice cap. Prices are configured estimates, not billing proofs. لا تسمية whole platform production-ready.

مراجعة إضافية للمرحلة الرابعة: export budget يُحسب ببايتات UTF-8، لا عدد حروف Unicode فقط؛ اختبار emoji multibyte يمنع تجاوز حد 10 MB عبر نص قصير ظاهريًا.

# تقرير المرحلة الخامسة — تنفيذ التشغيل، قبول الإصدار مفتوح

| الفحص المحلي | النتيجة |
|---|---|
| Backend النهائي | **124 passed**؛ 25 حالة تشغيل/أمان جديدة مع parameterization |
| المتصفح | **13 passed**: 10 السابقة + password/second-session، recovery/hash/no-SMTP، scoped token/revoke، desktop/390px/no overflow |
| Ruff F / strict TypeScript / Vite / pip check | نجح |
| BookForge vendor | **صفر ملفات معدلة**؛ manifest 26 ملفًا محفوظًا |
| تحميل محدود | 240 طلبًا، concurrency8، 48 queue jobs، 0 HTTP errors / duplicates / missing jobs، 0 model calls |
| أرقام التحميل | 0.704s و340.97req/s، p50 18.65ms وp95 33.08ms؛ قياس ASGI in-process محلي واحد، **ليس** توقع أداء شبكة/موديل/خادم إنتاج |
| اختبار مزود مدفوع | **لم يبدأ: حجبه النظام قبل تشغيل command**؛ صفر generation calls، ولا retry أو credential artifact أنشئ من الطلب المحجوب |
| موفر mock لاختبار حدود التقييم | طلبان فقط، outputs/usage مفحوصة، 429 دون retry، لا key في التقرير |
| Docker / Caddy / TLS | Docker غير مثبت محليًا؛ workflow مستقل يبني الصورة ويفحص config/non-root/health/401/persistent DB/backup/restore/Caddy config، الحالة تُراجع في PR |
| SMTP | outbox/claim/retry/purpose/expiry/one-use/reset/verification tested بمُرسِل محلي واضح؛ لا اختبار توصيل حقيقي أو domain/DNS |
| مراجعة بصرية | عرض PNG أعاد computer_helper_failed، لا اعتماد بصري للمراحل2–5 رغم DOM QA |

## دليل وظيفي جديد

- bearer hash-only, scoped published documents، expire/revoke/demote/archive، 60/min persisted limiter، لا browser/cookie privileges ولا owner/private routes أو mutation. Search يطبّق document scope قبل ranking؛ publication ثانية حقيقية تُرفض، URL للصورة/parts يعمل بالرمز نفسه.
- get_lesson يعيد جميع العناصر والمصدر الفعلي أو budget manifest بلا محتوى مقتطع؛ full/manifest/pages/chapter(null عند غيابه)/parts/assets/source JSON مختبرة.
- password change ومراجعة كلمة المرور الحالية/CSRF، invalidate كل session، login يرفض password hash قديمًا لمنع reset/login race. Reset/verify links hashed20min one-use، concurrency4 ينتج نجاحًا واحدًا، wrong-purpose/expired/reused ممنوعة.
- encrypted SMTP outbox، cancel superseded token، sender failure5 attempts، class-only errors/scrub secret؛ generic recovery وعدم ادعاء بريد مهيأ عندما لا يوجد، verified policy، email/name validation.
- actual HTTP chunked byte cap بلا Content-Length، origin/TrustedHosts، fresh private upload staging محفوظ وcrash orphan قديم محذوف.
- Backup يرفض live Services بقفل فعلي cross-process. Restore ينجح في login/vault decrypt/second vault/source/private file ويمنع overwrite، unsafe paths، symlink، duplicates، byte limits، missing key/hash mismatch. hash ليس توقيعًا ولا ثقة لملف خارجي.
- تحميل read auth/API بـ8concurrency ومطالبات queue48 فريدة؛ لا inference داخل benchmark. اختبارات صغيرة مع concurrency4 داخلة في pytest أيضًا.

## إصلاحات أثناء التطوير

اختبار byte cap الأول اختار260000bytes وهو أقل من256KiB؛ أصبح300000 وتأكد413. تنقل نفس الوثيقة إلى fragment recovery لم يعِد mount التطبيق؛ أضيف hashchange handler وتمحو الواجهة الرابط ثم تعرض النموذج. Docker backup/restore يحتاج writable owned mount points، أصبحت /backup و/restore و/data مهيأة UID10001. فحص الحاوية كشف مدخل Uvicorn مكسورًا (`bac.api.main:app` بلا object مُصدّر): أصبح `bac.api.main:create_app --factory` في Docker/Compose/README، واختبار subprocess يبدأ الخادم الفعلي ويثبت health/401/live maintenance lock/shutdown release. لا اعتماد نتائج factory-injection وحدها كدليل تشغيل للإنتاج. لا توجد نتيجة نجاح مدّعاة بعد فشل غير محلول.

## بوابة الإصدار

دون visual QA، smoke المزود المأذون بعد الحجب، مراجعة كتب حقيقية ومقيّمة، SMTP/TLS في بيئة المالك، ترخيص/native/security review مستقل وacceptance: **لا تسمية عامة Production-ready**. لا دفاع كامل من DNS rebinding/native exploits، ولا VM/seccomp scientifique، ولا ضمان معنى علمي لكل جواب. لا مفاتيح أو بيانات تشغيل أو PDF حقيقي committed.

External client regression: whole serialized payload budget (not text alone), deduplicated metadata/assets, no double copy of full Markdown and part contents. Oversized response refuses instead of claiming complete coverage.
