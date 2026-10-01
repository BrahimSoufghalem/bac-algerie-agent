# المرحلة 5 — التشغيل والأمان ووصول الوكلاء

## الحدود الصريحة

هذه قدرات تشغيلية منفّذة، وليست شهادة penetration test أو دقة تعليمية أو نشرًا فعليًا على نطاقك. اختبار المزود المأذون حُجب قبل التنفيذ، **صفر طلبات توليد مدفوعة**. الأداة الاختيارية مقيّدة بطلبين، دون retries، 2200 max output tokens مجموعًا؛ ترميز الصورة/المدخلات وتسعير المزود منفصل. إعادة محاولة حقيقية تحتاج تأكيد المستخدم بعد الحجب. المراجعة البصرية الجديدة ما زالت معلقة بسبب `computer_helper_failed`؛ اختبار DOM/هاتف ليس بديلًا للمراجعة البصرية. بيانات المثال اصطناعية وليست منهجًا رسميًا.

## تشغيل وإعادة فتح التطبيق

```bash
cp .env.example .env
# Linux + Docker Engine + Compose v2. أدخل إعدادات التشغيل، لا تحفظ .env في Git.
docker compose up --build -d
docker compose run --rm api python -m bac.cli bootstrap --email owner@example.org
```

افتح `http://127.0.0.1:8090` وسجّل الدخول بحساب المالك. في المرة التالية: `docker compose up -d` وافتح الرابط نفسه. الخدمات تعمل حتى لو أغلقت المتصفح. `docker compose stop` يحفظ volume `library`؛ **لا تستخدم down -v** لأنه يحذف البيانات. تعيد وظائف الاستخراج حالة الطابور المحفوظة، ولا تعيد الصفحات الناجحة؛ تشغيل تدريس مدفوع انقطع يُعلَّم INTERRUPTED دون إعادة تلقائية مدفوعة.

النتائج في volume داخل `/app/data`: `platform.sqlite3` للحسابات/الدردشة/المراجعة، `extraction/state.sqlite3` للاستخراج، `extraction/...` للأصل وصور الصفحات وJSON/crops/Markdown، `snapshots/...` للنشر الثابت، `private/...` للملفات المؤقتة. التشغيل دون Docker يستخدم `DATA_DIR` (افتراضي `./data`). احتفظ بالأصول وبـ **مفتاحي** `.encryption.key`؛ لا تكفي قاعدة البيانات وحدها. بيانات الدردشة ليست مشفّرة end-to-end، والنسخة الاحتياطية تحتوي مفاتيح التشفير والبيانات الخاصة.

## نشر HTTPS

اضبط `DOMAIN` إلى نطاق تملكه و`TLS_EMAIL`، وDNS للخادم، وافتح 80/443 فقط للمستخدمين. ثم:

```bash
docker compose -f compose.yaml -f compose.production.yaml up --build -d
```

Caddy يتولى TLS/HSTS وبث SSE بدون buffering. API على loopback فقط؛ overlay يفرض Secure cookies وTrusted Hosts وPUBLIC_ORIGIN. حافظ على loopback: trust للـ forwarded headers مخصص للـ proxy المحلي الموثوق وليس لبورت API عام. الحاوية غير root، read-only root filesystem، no-new-privileges، cap-drop، tmpfs وmemory/CPU/PID limits. ملفات المستخدم في volume دائم؛ SQLite **خادم Linux واحد فقط** وليس replicas متعددة أو NFS. زد العمال وفق ذاكرة الجهاز/المزود، لا عددًا تعسفيًا؛ برامج الحساب لها حدود إضافية. worker مطلوب للاستخراج/الدردشة/Bريد وتنظيف TTL.

CI يبني الصورة ويفحص Compose/UID/health/401/persistence؛ شهادات TLS والـ DNS وSMTP الحقيقي لا يثبتها CI. Docker غير متاح محليًا. راجع PyMuPDF AGPL/commercial قبل توزيع تجاري. راقب مساحة القرص، audit، errors، outbox، usage؛ لا تعرض tracebacks أو ملفات DB/المفاتيح عبر proxy.

## حسابات وكلمات مرور وبريد

- scrypt + cookie HttpOnly/SameSite Strict + CSRF + origin check. كلمة مرور 12–256 حرفًا.
- لوحة **أمان الحساب** تغير كلمة المرور بمراجعة كلمة المرور الحالية؛ تلغي كل الجلسات/روابط الاستعادة ورموز الوكلاء الخاصة بالمصدر وتوقف التشغيلات الجارية. إلغاء الجلسات متاح مستقلًا.
- SMTP اختياري: `SMTP_HOST/PORT/FROM/USER/PASSWORD`, `PUBLIC_ORIGIN=https://...`. STARTTLS إلزامي، شهادة TLS متحقق منها، timeout 10s. لا fallback لرسائل plaintext. `REQUIRE_VERIFIED_EMAIL=true` اختياري، يتطلب SMTP.
- تسجيل طالب جديد يرسل verification إذا كان البريد مهيأ. recovery والverification بطلب صريح، استجابة عامة لا تكشف وجود البريد، معدلات IP/address، صلاحية20 دقيقة، hash في DB، استخدام واحد transaction-safe. الرابط يحمل fragment؛ تمحوه الواجهة بعد تحميله، ولا يظهر في request URL أو server access log.
- البريد في outbox مشفّر. worker يطالب بlease، 5 محاولات كحد أقصى مع backoff، scrubs secret بعد نجاح/إلغاء/فشل نهائي. `SENT` تعني قبول SMTP وليست وصولًا مؤكّدًا لصندوق المستلم؛ crash بعد الإرسال قد يكرر الرسالة لكن الرابط نفسه one-use. الأخطاء نوع exception فقط، لا SMTP password/link/address.
- إذا لم تُهيأ SMTP تعرض الواجهة ذلك، ولا تدعي إرسال بريد. operator على الخادم يمكنه `python -m bac.cli reset-password --email ...` (getpass لا command line)، أو `verify-email` كتأكيد بشري موثّق في audit. bootstrap يتأكد بالبريد يدويًا باعتباره إجراء مشغّل موثوقًا؛ لا تتحول الحسابات العامة إلى verified تلقائيًا.

## الوكلاء الخارجيون — العقد نفسه وليس owner token

المالك يفتح **وصول الوكلاء** ويختار كتبًا **منشورة** محددة وصلاحية1–365 يومًا. لا اختيار شامل ضمني. رمز يظهر مرة واحدة ويُحفظ SHA-256 فقط، ≥256bit entropy، قابل للإلغاء، 60 طلب/minute لكل رمز، أقصى25 رمزًا نشطًا. تعطيل/تغيير دور المصدر أو أرشفة/تغيير نشر الكتاب يوقف الوصول فورًا للطلبات الجديدة. بيانات أعيدت سابقًا لا يمكن استرجاعها من وكيل خارجي.

```text
Authorization: Bearer <SERVICE_TOKEN>
GET /api/agent/capabilities
GET /api/agent/books
GET /api/agent/books/{book_id}/toc?kind=lesson
GET /api/agent/search?q=...&book_id=...
GET /api/agent/get_lesson/{lesson_id}?max_chars=60000
GET /api/agent/nodes/{id}/bundle
GET /api/agent/nodes/{lesson_id}/parts
GET /api/agent/parts/{part_id}
GET /api/agent/assets/{asset_id}/metadata
GET /api/agent/assets/{asset_id}
GET /api/agent/books/{book_id}/pages/{pdf_page}/json?file_id=...
GET /api/agent/books/{book_id}/pages/{pdf_page}?file_id=...
```

`get_lesson` يعيد book/chapter(أو null إذا لا يوجد)/lesson/full content/pages/figures/tables/equations/ancestors/sources/assets. النسخ والأرقام الأصلية ثابتة، روابط الصور تستعمل `/api/agent/assets` لا routes المتصفح التي يرفضها bearer. إذا تجاوز **payload كاملًا** max_chars (1000–500000) يعيد manifest URL و`content_complete:false` بلا نص مقتطع أو citation credit مصطنع. اقرأ كل الأجزاء أو حدّد الجزء المطلوب واعترف بنطاق ما قرأته. جدول/معادلة لا تنقسم منتصف العنصر. exam+solution وexercise_collection تبقى حزم كاملة. الوكيل التعليمي الداخلي يحتفظ بقياس ميزانية السياق قبل source credit في docs/RETRIEVAL.md؛ API الخارجي لا يعرف سياق وكيلك.

كل route يتحقق من scope/current publication قبل القراءة؛ search يطبق scope **قبل** ranking. bearer مرفوض في كل routes الخاصة/المالك/المتصفح وحتى recovery، لا POST/DELETE أو وصول لمزوّد. لا تضع الرمز في URL/browser storage/source code. النموذج يتعامل مع الكتاب كبيانات غير موثوقة، لا تعليمات عليا. [client قابل للتشغيل](../examples/agent_client.py) يستخدم env/TLS وحدودًا، دون أي model call ضمن الاسترجاع.

## نسخة احتياطية واستعادة مجرّبة

**أوقف API+worker أولًا**؛ قفل مشترك بعمر العملية، والنسخ يحتاج قفلًا حصريًا. يشمل DBs+keys+originals+rasters+JSON+assets+Markdown+snapshots+private records/files. WAL checkpoint ثم zip + SHA256 لكل ملف + manifest؛ 0600 للملف. ضع النسخة خارج DATA_DIR وانقلها إلى مخزن مشفّر مستقل؛ hashes للتحقق من السلامة، **ليست signature أو إثبات ثقة**.

تشغيل مباشر:
```bash
# أوقف خدماتك/عمليات uvicorn وworker ثم:
python -m bac.cli backup --output /secure-backups/masar-2026-10-01.zip
python -m bac.cli restore --archive /secure-backups/masar-2026-10-01.zip --destination /srv/masar-restored
# destination جديد لا يوجد مسبقًا؛ اضبط DATA_DIR إليه وشغّل migration ثم API+worker.
```

Docker:
```bash
docker compose stop api worker
# /srv/backups يجب أن يكون قابلاً للكتابة لـ UID10001 ومجلدًا خاصًا.
docker compose run --rm --no-deps -v /srv/backups:/backup api python -m bac.cli backup --output /backup/masar.zip
# الاستعادة إلى subdirectory جديد داخل volume آخر، لا الكتابة فوق volume المصدر:
docker volume create masar-restore-stage
docker compose run --rm --no-deps -v /srv/backups:/backup:ro -v masar-restore-stage:/restore api python -m bac.cli restore --archive /backup/masar.zip --destination /restore/new-data
# استخدم المجلد الجديد كـ bind mount لـ /app/data بعد التحقق؛ أبقِ المصدر القديم.
docker compose up -d
```

الاستعادة ترفض destination قائمًا، traversal/absolute/Windows/backslash/duplicates/symlinks/zip bombs ومفاتيح ناقصة/DB تالفة/hash mismatch؛ staging ثم atomic rename. الحدود5GiB uncompressed/100000ملف الافتراضية؛ المكتبات الأكبر تحتاج اختيارًا متعمدًا مثل `--max-restore-gib 50 --max-restore-files 500000`. لا تستعد zip من مصدر غير موثوق ولو صحت hashes. اختبر استعادة شهرية فعلية في staging ولا تحذف آخر نسخة جيدة. الاختبارات أثبتت استعادة login وفك التشفير وكتاب منشور ومصادره والمفتاح الثاني والملف الخاص، لا مجرد فتح zip.

## فحص التحميل والمزود

```bash
python -m bac.ops.load --requests 240 --concurrency 8 --runs 48 --output /tmp/load.json
# منفصل، اختيار صريح وتكلفة فعلية من رصيدك، secrets في env فقط:
python -m bac.ops.evaluate_provider --confirm-cost --image /secure/test-page.png --output /secure/provider-report.json
```

الأول SQLite + ASGI محلي ببيانات مؤقتة وبدون أي API للموديل؛ ليس network/proxy/load benchmark إنتاجيًا. الثاني يحتاج MODEL_API_KEY/BASE_URL/NAME ولا يخمّن نموذجًا؛ لا retry، يعرض schema/bbox/لغة وtool compatibility/مصدر ثابت/رقم بسيط؛ لا يثبت فهم منهج أو حفظ نص كامل أو صحة جواب علمي. يحفظ تقريرًا دون key أو صورة/إجابة كاملة؛ راجع يدويًا مع كتب مرخّصة حقيقية قبل release.
