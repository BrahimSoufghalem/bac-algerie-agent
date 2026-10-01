# قرارات المرحلة الأولى

1. **Modular monolith** Python/FastAPI + React/TypeScript. خدمات API وworker منفصلة من نفس مصدر الكود؛ أبسط من microservices في هذه المرحلة.
2. **SQLite/WAL** للتشغيل المحلي مع معاملات `BEGIN IMMEDIATE`، وFilesystem للمصادر والمخرجات. قاعدة platform منفصلة عن state الخاصة بـ BookForge، بما يحافظ على فصل البيانات والصلاحيات.
3. **إعادة استخدام مثبتة**: نسخة vendor من 25 ملفًا من BookForge بعد اختبار baseline (32 passed)، مع تعديل namespace ومسار subprocess فقط في البداية. `bookforge-reuse.json` يحوي SHA-256 الأصل والمعدل؛ الملف الأصلي لم يتغير. ملف fixture الاصطناعي أيضًا مأخوذ من BookForge مع احتفاظ الترخيص.
4. **لا حذف ولا auto-publish**: الأصل يبقى، Vision ينتج JSON، Python يقص ويكتب Markdown، ثم اعتماد مالك صريح وsnapshot غير قابل للتغيير. بيانات المسودة لا توجد في فهرس الطلاب. النسخة الحالية مؤشر ذري قابل للتبديل والأرشفة.
5. **نموذجان بإعداد مستقل**: slot للتدريس وslot للاستخراج. إعداد immutable لكل تشغيل؛ key ciphertext فقط في DB ومفتاح vault خارج المصدر، محمي بصلاحيات filesystem.
6. **نموذج واحد وحدود حقيقية**: مصدر واحد للموديل في كل run، أدوات فقط من allowlist، stop يعطّل الطلب النشط، step/time/context/tool caps ودليل أحداث محفوظ. لا polling للعرض يوهم بعمليات لا تحدث، ولا chain-of-thought معروض.
7. **ميزانية الحروف صريحة**: حدود char خفيفة ومحمولة بدل تقدير غير دقيق للتوكن لكل نموذج. الأرقام المالية لا تستنتج إلا من usage الفعلي وأسعار معطاة. مزوّد لا يعيد usage يتركه null.
8. **الكتب تبقى بهيكلها**: درس/وحدة فقط إذا موجودين. أُضيف في المرحلة الثانية نمط امتحان/حل مطابق وسلسلة تمارين كاملة، دون تحويل الأسئلة إلى دروس. الواجهة تتيح الأنواع الأربعة؛ الكتب فقط تستخدم هيكل BookForge.
9. **الأذونات على الخادم**: التسجيل student فقط، كل chat/run مملوك لصاحبه، owner وحده يرفع ويعتمد وينشر. Origin/CSRF للكتابة، cookies HttpOnly، تعليمات الوثائق مدخلات غير موثوقة.
10. **التخزين المحلي أولًا**: DB وfiles ومفتاح vault نسخة احتياطية واحدة. SQLite ليس قاعدة متعددة المناطق. scale العام وstorage adapters وتوكنات خدمة أدق والتقييم العلمي مراحل لاحقة وليست وعود أداء حالية.
11. **فصل الاختبار عن الإنتاج**: test factories inject فقط في tests. entry point الإنتاج يستخدم HTTP provider الحقيقي، لا إجابات canned ولا mock implicit. لم نرسل طلبًا مدفوعًا للمزوّد في تنفيذ هذه المرحلة.

## قرارات المرحلة الثانية

- Queue BookForge وvendor لا يتغيران؛ raw PDF deduplicated، primary/solution file identities ونطاقات نشر مستقلة.
- fingerprint للمصدر/الهوية، تأكيد مالك صريح مع دليل، mismatch المعروف يرفض، missing solution صريح. أي تغيير يوجب تأكيدًا ومراجعة جديدين.
- snapshot v2 نسخ مستقلة للـPDF/raster/JSON/Markdown/crops؛ publish يبدل metadata والمؤشر ذريًا. metadata المسودة لا تغيّر النشر.
- lesson parts حدود عناصر كاملة هدفها 8000 حرف لا حد مضمون للعنصر الطويل؛ JSON النهائي يخضع لميزانية الأداة. لا بتر للعنصر الزائد ولا تفتيت للحزم.
- cache محدود للملفات المعتمدة، authorization قبل lookup؛ sources لا تحصل على credit إلا بعد دخول السياق.
- BM25 فهرسة نص مباشر بدل تكرار جميع طبقات الكتاب. adapters المستقبلية لا تفرض قاعدة vector. لا ادعاء تفوق بلا evaluation حقيقي.
- بديل rendering محلي عند غياب سكربت capture المجمّع بعد إعادة تشغيل البيئة؛ تم توليد صور فعلية، لكن أداة عرضها تعطلت؛ المراجعة البصرية الجديدة معلقة ولا تُستبدل بنجاح الاختبارات.

## قرارات المرحلة الثالثة

- SymPy 1.14.0/mpmath 1.3.0 مع pinned versions وتراخيص BSD. Build من AST allowlist دون eval/sympify للنص غير الموثوق.
- numeric Python-shaped interpreter بدل arbitrary Python: أبسط حد قدرات قابل للمراجعة. resource/isolated child limits لا تعني sandbox نظام كامل؛ إذا توسع التنفيذ يجب sandbox خارجي مع security evaluation.
- calculator rational/50digits، programs binary64، affine temperature منفصلة عن delta؛ assumptions/domain ولا verification شامل من النجاح العددي.
- server-owned immutable results مرتبطة بالrun/user/chat. Failed/inconclusive تبقى مرئية ولو أغفلها النموذج. لا إعادة استعمال result ID قديم كشهادة جديدة.
- SVG مكوّنات React من JSON bounded، لا executable chart markup. plotted program arrays مرجع مباشر، diagram equal scales. مصدر البيانات/حدود التحقق يظهران.
- لا dependency chart كبيرة أو vector service. API typed blocks/storage والقدرات العلمية modular؛ vendor BookForge لا يتغير.
