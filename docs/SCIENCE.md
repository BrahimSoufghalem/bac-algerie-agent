# عقد الحساب والتحقق والرسم — المرحلة الثالثة

## أدوات مستقلة، لا تصديق من النموذج لنفسه

| الأداة | الدلالة |
|---|---|
| `calculate` | تعبير عددي حقيقي، literals عشرية كـrational exact، تقييم 50 رقمًا |
| `verify_calculation` | مقارنة المحسوب والمتوقع بتسامح مطلق ونسبي صريحين |
| `verify_equation` | تعويض بالقيم وفحص lhs/rhs وشروط eq/ne/lt/le/gt/ge؛ القيمة المفقودة inconclusive |
| `symbolic_math` | simplify/differentiate/integrate/solve/compare بواسطة SymPy، رموز real وافتراض positive اختياري |
| `convert_units` | تحويل SI بسجل وحدات صريح محدود؛ لا guessing لتعريف وحدة |
| `verify_dimensions` | توافق الأبعاد فقط، لا تحقق من القيم أو تفسير الظاهرة |
| `run_scientific_code` | مفسّر numeric AST يشبه جزءًا من Python، ليس Python عامًا |
| `plot_function` | أخذ عينات من دالة في مجال حقيقي معلوم، بفصل المجالات المنقطعة |
| `plot_data` | line/scatter/bar من قيم مقدّمة؛ shape/finite checks ليست توثيق مصدر |
| `plot_from_result` | رسم arrays المخرجات الأصلية للكود في التشغيل الحالي دون إعادة نسخها من النموذج |
| `draw_diagram` | segment/vector/circle/point بحدود وإحداثيات صريحة؛ رسم هندسي متساوي مقياس المحورين |

`computed` يعني إجراء حساب/تحويل/رسم؛ ليس `passed`. `passed` يخص الفحص المحدد ومدخلاته فقط. `failed` و`inconclusive` لا يصبحان شارة نجاح. نتيجة خاطئة/غير محسومة تُضاف ككتلة فعلية حتى لو أغفلها النموذج في render_answer. الربط بمعادلة دليل مدخلات، لا ضمان تطابق كل صياغة المعادلة أو الشرح مع تلك المدخلات.

## أمثلة

```json
{"expression":"m*c*dT","values":{"m":"2","c":"4200","dT":"10"},"expected":"84000"}
```

```json
{"lhs":"P*V","rhs":"n*R*T","units":{"P":"Pa","V":"m**3","n":"mol","R":"J/(mol*K)","T":"K"}}
```

المثال الأول لـverify_calculation والثاني لـverify_dimensions. لا يستنتج التطبيق أن المعطيات تخص سؤالًا أصليًا أو أنها كافية دون تصريح. `x/x` عند x=0 مرفوض قبل cancellation. `sqrt(x**2)` لا يصبح x لرمز real دون positive assumption. solve يقيّد الحلول بالمجال الحقيقي والأصل وبافتراض positivity؛ compare لا يصدّق مجالات مختلفة/مجهولة أو multivariate غير مدعوم. التكامل غير المحدد يعيد primitive دون +C؛ نتيجة غير محلولة تبقى inconclusive.

### الكود العلمي المقيّد

```python
xs = linspace(0, 2, 21)
ys = []
for t in xs:
    ys = ys + [v*t + a*t**2/2]
emit("time", xs)
emit("distance", ys)
```

inputs: `{"v":3,"a":2}`. عند t=2 تكون distance=10. numeric subset يستخدم binary64، لا دقة rational للكود؛ الحساب calculator مستقل عنه. المتاح: assignments، for على numeric list محدود، if بمقارنة مفردة، arithmetic، indexing lists، concatenation محدودة، range/linspace، sum/min/max/len وsqrt/sin/cos/tan/exp/log/abs/round، emit(label,value). لا imports، attributes، comprehensions، generators، while، def، classes، exceptions أو eval/exec. أسماء المتغيرات ASCII واضحة؛ النص العربي يبقى في الشرح والعناوين.

## الحدود وعزل التنفيذ

- Linux/POSIX مع `resource` مطلوب. لا fallback إلى تنفيذ غير محدود داخل process الرئيسي.
- fixed trusted bootstrap و`python -I`؛ لا تضمين مدخلات المستخدم في command/script/environment. environment لا يرث مفاتيح نموذج/Vault. كل النص غير الموثوق يُحلَّل بـAST ويُفسَّر بواسطة allowlist، **لا compile/exec/eval للكود المولد**. SymPy يُبنى من AST، لا sympify/parse_expr على النص غير الموثوق.
- process منفصل لكل أداة: wall=6s، CPU=4s، address space=256MiB افتراضيًا، no core dump، file-write limit=0، file-descriptor cap=32. تُقتل العملية عند deadline، ولا تُمنح نتيجة ناجحة.
- `SCIENCE_TIMEOUT` 2–15، CPU 1–wall، memory 128–512MiB قابلة للإعداد. أقصى عمليتين علميتين لكل worker process، فوق حدود run/tool/steps القائمة. ليست semaphore موزعة بين أجهزة.
- 500 AST nodes للكود، 12000 interpreted steps، 2000 iterations، 401 عنصرًا/list، 12 outputs، 32 variable تقريبًا. bounds على literal/exponent/expression/input/output. child output cap≤18000 حرف، input≤17000؛ wrapper النهائي يخضع كذلك لـMAX_TOOL_CHARS. التجاوز رفض صريح بلا بتر/credit.
- إيقاف run يوقف متابعة الوكيل. thread subprocess الجاري قد يستهلك حتى hard deadline؛ لا حفظ/credit ناجح بعد cancel flag. لا وعد بإيقاف عملية الحساب لحظيًا.
- **هذا capability-limited language boundary مع hard resource process، وليس VM/seccomp أو تنفيذًا آمنًا لـPython عام.** child يستخدم هوية خدمة التطبيق؛ imports التطبيق/المكتبات الموثوقة تحتاج قراءة ملفاتها عند startup. البرنامج المولد نفسه لا يملك أي API للملفات/الشبكة/OS. ثغرات المكتبات الأصلية أو kernel ليست محسومة بهذه الاختبارات. لا توسّع allowlist إلى arbitrary imports/exec؛ يلزم sandbox خارجي معزول وتقييم أمني قبل ذلك.

## الوحدات

السجل الحالي: kg/g/mg، m/cm/mm/km، s/min/h، A، K/delta_degC، mol، cd، rad/dimensionless، N/J/W، Pa/kPa/MPa/bar/atm، L/mL، Hz/C/V/ohm/eV، وقوى/ضرب/قسمة مركبة. unités أخرى غير معروفة ترفض بدل invent conversion. `degC` أو `°C` مستقلان للتحويل المطلق (+273.15)؛ درجة الفرق `delta_degC`. لا degC داخل معادلة مركبة؛ حوّل absolute إلى K أولًا. تحويل قيمة temperature لا يثبت معقوليتها الفيزيائية. لا تحويل العملات أو الوحدات غير القياسية/كل prefixes تلقائيًا.

## أدلة محفوظة وواجهة آمنة

- جدول `scientific_results` migration003 يحفظ user/chat/run، tool، inputs، output، SHA256 ووقت التنفيذ. هو trace علمي خاص بالمحادثة، لا مصدر كتاب رسمي ولا cache provider.
- `GET /api/science/results/{id}` يتطلب صاحب المحادثة؛ طالب آخر أو مستخدم غير مصادق لا يقرأه. SHA256 فحص اتساق للبيانات، ليس توقيعًا ضد تعديل DB من المدير. حذف المحادثة يحذف الأدلة التابعة.
- `verification` و`graph` في render_answer يقبلان **result_id فقط** من التشغيل الحالي. `result` payload من النموذج مرفوض؛ server يحقن النتيجة الأصلية. equations تدعم result_ids محملة حقيقية. إعادة فتح المتصفح تعرض blocks المخزنة نفسها؛ run جديد يعيد الحساب عند الحاجة ولا يحصل على badge من ID قديم.
- الرسوم safe JSON→React SVG، لا arbitrary SVG/HTML/JS أو external URLs. تفاعلية بإشارة مؤشر أو slider keyboard، values table، labels/unit text وorigin/caveat. المخطط الهندسي لا يدّعي تصوير pixel للمصدر. Domain غير مدعوم للرسم يُرفض بدل توصيل منحنى وهمي عبره؛ sampling لا يثبت extrema/continuity.
- BookForge/vendor ومصادر الصور الأصلية لم تتغير. image blocks السابقة تظل من published assets فقط؛ graph ليس بديلًا للصورة الأصلية.

## ما لا يزال غير مثبت

الفحوص تختبر المدخلات المحددة؛ لا ضمان أن النموذج فهم السؤال، لم يحذف شرطًا أو قدّم تفسيرًا علميًا صحيحًا. Multivariate/domain proofs عامة، real-model lesson evaluations، الوحدات غير المدعومة، load/DoS/security audit الكامل، deployment/backup وscoped service tokens ليست منجزات تلقائية. لا native arbitrary code، لا مخططات 3D/chemistry renderer. لا طلبات نموذج مدفوعة جديدة في تنفيذ هذه المرحلة. المراجعة البصرية الجديدة معلقة بسبب عطل أداة view_image، رغم التقاط صور حقيقية ونجاح functional E2E.
