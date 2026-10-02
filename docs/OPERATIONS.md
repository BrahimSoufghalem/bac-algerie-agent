# المرحلة 5 — التشغيل والأمان ووصول الوكلاء

## الحدود الصريحة

هذه قدرات تشغيلية وليست شهادة أمن أو دقة تعليمية أو نشرًا على جهاز المستخدم. راجع [أحدث اختبار فعلي وحدوده](acceptance/private-autonomous-chat.md). البيانات الاصطناعية في اختبارات المتصفح ليست منهجًا رسميًا.

## تشغيل وإعادة فتح التطبيق

```bash
cp .env.example .env
# Linux + Docker Engine + Compose v2. أدخل إعدادات التشغيل، لا تحفظ .env في Git.
docker compose up --build -d
docker compose run --rm api python -m bac.cli bootstrap --email owner@example.org
```

افتح `http://127.0.0.1:8090` وسجّل الدخول بحساب المالك. في المرة التالية: `docker compose up -d` وافتح الرابط نفسه. الخدمات تعمل حتى لو أغلقت المتصفح. `docker compose stop` يحفظ volume `library`؛ **لا تستخدم down -v** لأنه يحذف البيانات. تعيد وظائف الاستخراج حالة الطابور المحفوظة، ولا تعيد الصفحات الناجحة؛ تشغيل تدريس مدفوع انقطع يُعلَّم INTERRUPTED دون إعادة تلقائية مدفوعة.

النتائج في volume داخل `/app/data`: `platform.sqlite3` للحسابات/الدردشة/المراجعة، `extraction/state.sqlite3` للاستخراج، `extraction/...` للأصل وصور الصفحات وJSON/crops/Markdown، `snapshots/...` للنشر الثابت، `private/...` للملفات المؤقتة. المدخل API الفعلي هو `uvicorn bac.api.main:create_app --factory --host 127.0.0.1 --port 8090`؛ التشغيل دون Docker يستخدم `DATA_DIR` (افتراضي `./data`). احتفظ بالأصول وبـ **مفتاحي** `.encryption.key`؛ لا تكفي قاعدة البيانات وحدها. بيانات الدردشة ليست مشفّرة end-to-end، والنسخة الاحتياطية تحتوي مفاتيح التشفير والبيانات الخاصة.

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

## مراجع سرية، لا وكلاء خارجيون

كل طرق `/api/library/*` و`/api/agent/*` تتطلب جلسة المالك؛ الطالب والأستاذ لا يقرآنها حتى بمعرّفات صحيحة. service tokens القديمة مسحوبة وإنشاؤها مرفوض. عامل التدريس يقرأ النسخ المعتمدة داخليًا، ويستطيع فحص pixels دون نشرها في المحادثة. الأدوات والسجلات التقنية لا تُعرض لأي دور. `/api/science/*` وOpenAPI غير متاحين في التطبيق العام.

### تحديث النسخة الموجودة بأمان

1. أوقف API وworker وخذ backup كاملًا بـDBs وkeys وPDFs وsnapshots، واحفظه خارج مجلد البيانات ولا تشاركه.
2. حدّث الكود ثم شغّل API وworker من النسخة نفسها. Docker: `docker compose up -d --build api worker` بعد `git pull --ff-only`؛ لا `down -v`.
3. migration006 يضيف origin للملاحظات، يعزل الملاحظات اليدوية القديمة، يسحب المفاتيح الخارجية ويحذف سجلات التدريب الذاتي. العودة للنسخة القديمة تتطلب استعادة النسخة الاحتياطية والكود القديم معًا، لا حذف migration.
4. احفظ مفتاح المزود الحالي في إعداد النماذج على جهازك؛ حفظه في بيئة الاختبار لا يغيّر localhost الخاص بك. لا تضعه في Git أو ملف توثيق.
5. `MAX_RUN_STEPS` القديم يُتجاهل؛ `MAX_RUN_SECONDS=180` افتراضيًا، قابل للضبط حتى 600. تكرار لا يحرز تقدمًا والسياق والحساب والحدود اليومية ما زالت تضبط التشغيل. لا تشغيل مدفوع لا نهائي ولا retries خفية.
6. اختبر سؤالًا عاديًا، تبسيطه، الإيقاف، إعادة فتح المحادثة، عدم وجود مكتبة/صور أصلية/نشاط أدوات، وملاحظات القراءة فقط على جهاز النشر الفعلي.

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
