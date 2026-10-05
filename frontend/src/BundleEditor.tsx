import React, { useEffect, useState } from "react";
import {
  IdentityChoices,
  emptyCatalogue,
  StudyCatalogue,
  sourceIdentity,
} from "./StudyChoices";
export default function BundleEditor({
  version,
  api,
  action,
  refresh,
  onClone,
}: {
  version: any;
  api: any;
  action: (fn: () => Promise<void>) => void;
  refresh: () => Promise<void>;
  onClone: (v: any) => void;
}) {
  const [catalogue, setCatalogue] = useState<StudyCatalogue>(emptyCatalogue);
  useEffect(() => {
    api("/api/study/catalogue")
      .then(setCatalogue)
      .catch(() => {});
  }, []);
  const [file, setFile] = useState<File | null>(null),
    [combined, setCombined] = useState(false),
    [first, setFirst] = useState(1),
    [last, setLast] = useState(1);
  const [evidence, setEvidence] = useState(""),
    [matching, setMatching] = useState(false),
    [provenance, setProvenance] = useState(false);
  const [metadata, setMetadata] = useState({
    subject: "",
    track: "",
    tracks: [] as string[],
    year: "",
    session: "",
    exam_type: "",
    source: "",
    designation: "provided",
  });
  const [draft, setDraft] = useState<any>(version.metadata);
  const [range, setRange] = useState({
    file_id: "",
    first_page: 1,
    last_page: 1,
  });
  const solution = version.files?.find((f: any) => f.role === "solution");
  const editable =
    !["REVIEWED", "PUBLISHED"].includes(version.status) &&
    !version.files?.some((f: any) => f.extraction_status === "PROCESSING");
  useEffect(() => {
    setDraft(version.metadata);
    setMetadata({
      subject: version.metadata.subject,
      track: version.metadata.track,
      tracks: version.metadata.tracks || [version.metadata.track],
      year: version.metadata.year || "",
      session: version.metadata.session || "",
      exam_type: version.metadata.exam_type || "",
      source: "",
      designation: "provided",
    });
    const f = version.files?.[0];
    if (f)
      setRange({
        file_id: f.id,
        first_page: f.first_page,
        last_page: f.last_page,
      });
    setMatching(false);
    setProvenance(false);
    setEvidence("");
    setFile(null);
  }, [version.id]);
  const path = "/api/owner/versions/" + version.id;
  const clean = (m: any) => ({
    ...m,
    ...sourceIdentity(catalogue, m),
    year: m.year || null,
    session: m.session || null,
    exam_type: m.exam_type || null,
  });
  return (
    <div className="bundle-editor">
      <div className="section-heading">
        <h3>هوية المصدر وملفاته</h3>
        <button
          disabled={editable}
          onClick={() =>
            action(async () => {
              await refresh();
              onClone(await api(path + "/clone", "POST", {}));
            })
          }
        >
          إنشاء نسخة جديدة
        </button>
      </div>
      <p className="muted">
        الكتاب يحتفظ بفهرسه الحقيقي. الامتحان وسلسلة التمارين حزمة كاملة؛ لا
        تُحوّل الأسئلة إلى دروس مصطنعة.
      </p>
      <details>
        <summary>تعديل هوية المسودة</summary>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            action(async () => {
              await api(path + "/metadata", "PATCH", clean(draft));
              await refresh();
            });
          }}
        >
          <label>
            نوع محتوى المسودة
            <select
              disabled={!editable}
              value={
                draft.content_type ||
                (
                  {
                    book: "textbook",
                    reference: "textbook",
                    exam: "school_tests",
                    exercise_collection: "exercises",
                  } as any
                )[draft.kind]
              }
              onChange={(e) => {
                const t = catalogue.content_types.find(
                  (x) => x.id === e.target.value,
                )!;
                setDraft({ ...draft, content_type: t.id, kind: t.kind });
              }}
            >
              {catalogue.content_types.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label}
                </option>
              ))}
            </select>
          </label>
          <div className="form-columns">
            <IdentityChoices
              catalogue={catalogue}
              value={draft}
              onChange={setDraft}
              disabled={!editable}
              labels={["شعب المسودة", "مادة المسودة"]}
            />
            {[
              ["title", "عنوان المسودة"],

              ["year", "سنة المسودة"],
              ["session", "دورة المسودة"],
              ["exam_type", "نوع امتحان المسودة"],
              ["source", "مرجع المسودة"],
            ].map(([key, label]) => (
              <label key={key}>
                {label}
                <input
                  value={draft[key] || ""}
                  required={["title", "subject", "track"].includes(key)}
                  disabled={!editable}
                  onChange={(e) =>
                    setDraft({ ...draft, [key]: e.target.value })
                  }
                />
              </label>
            ))}
          </div>
          <button disabled={!editable}>حفظ هوية المسودة</button>
        </form>
      </details>
      <div className="source-files">
        {version.files?.map((f: any) => (
          <div key={f.id}>
            <strong>
              {f.role === "primary" ? "الموضوع / المصدر" : "الحل المرفق"}
            </strong>
            <span>{f.filename}</span>
            <bdi dir="ltr">
              {f.first_page}–{f.last_page} / {f.page_count}
            </bdi>
            <span className="muted">
              {f.extraction_status} ·{" "}
              {f.verification === "owner_verified"
                ? "مطابقة أكدها المالك"
                : f.verification === "pending"
                  ? "المطابقة لم تُؤكّد بعد"
                  : ""}
            </span>
          </div>
        ))}
      </div>
      {version.metadata.kind !== "book" && (
        <details>
          <summary>اختيار نطاق الصفحات — PDF مدمج</summary>
          <p className="muted">
            حدد نطاق الموضوع أولًا ثم نطاق الحل. يجب ألا يتداخلا. المعالجة تتم
            للـPDF الخام مرة واحدة؛ إعادة الفاشلة تشمل ملفه كله.
          </p>
          <form
            className="range-form"
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                await api(
                  path +
                    "/files/" +
                    encodeURIComponent(range.file_id) +
                    "/range",
                  "PATCH",
                  { first_page: range.first_page, last_page: range.last_page },
                );
                await refresh();
              });
            }}
          >
            <label>
              ملف النطاق
              <select
                value={range.file_id}
                disabled={!editable}
                onChange={(e) => {
                  const f = version.files.find(
                    (f: any) => f.id === e.target.value,
                  );
                  setRange({
                    file_id: f.id,
                    first_page: f.first_page,
                    last_page: f.last_page,
                  });
                }}
              >
                {version.files.map((f: any) => (
                  <option key={f.id} value={f.id}>
                    {f.role === "primary" ? "الموضوع" : "الحل"} · {f.filename}
                  </option>
                ))}
              </select>
            </label>
            <div className="form-columns">
              <label>
                أول صفحة في النطاق
                <input
                  type="number"
                  min="1"
                  value={range.first_page}
                  disabled={!editable}
                  onChange={(e) =>
                    setRange({ ...range, first_page: Number(e.target.value) })
                  }
                />
              </label>
              <label>
                آخر صفحة في النطاق
                <input
                  type="number"
                  min="1"
                  value={range.last_page}
                  disabled={!editable}
                  onChange={(e) =>
                    setRange({ ...range, last_page: Number(e.target.value) })
                  }
                />
              </label>
            </div>
            <button disabled={!editable}>حفظ نطاق الصفحات</button>
          </form>
        </details>
      )}
      {["exam", "exercise_collection"].includes(version.metadata.kind) && (
        <>
          <h3>الحل المطابق — اختياري</h3>
          <p className="muted">
            إن لم تُرفق حلًا يظهر «الحل غير متاح». لا نبحث عن حل مشابه بالعنوان
            ولا نخترع حلًا رسميًا.
          </p>
          {!solution ? (
            <form
              className="solution-form"
              onSubmit={(e) => {
                e.preventDefault();
                action(async () => {
                  if (combined)
                    await api(path + "/solution/range", "POST", {
                      metadata: clean(metadata),
                      page_range: { first_page: first, last_page: last },
                    });
                  else {
                    const data = new FormData();
                    data.append("file", file!);
                    data.append("metadata", JSON.stringify(clean(metadata)));
                    await api(path + "/solution/upload", "POST", data);
                  }
                  await refresh();
                });
              }}
            >
              <label className="check">
                <input
                  type="checkbox"
                  checked={combined}
                  disabled={!editable}
                  onChange={(e) => setCombined(e.target.checked)}
                />
                الحل موجود داخل PDF الموضوع نفسه
              </label>
              {combined ? (
                <div className="form-columns">
                  <label>
                    أول صفحة للحل
                    <input
                      type="number"
                      min="1"
                      value={first}
                      onChange={(e) => setFirst(Number(e.target.value))}
                    />
                  </label>
                  <label>
                    آخر صفحة للحل
                    <input
                      type="number"
                      min="1"
                      value={last}
                      onChange={(e) => setLast(Number(e.target.value))}
                    />
                  </label>
                </div>
              ) : (
                <label>
                  ملف PDF للحل
                  <input
                    type="file"
                    accept=".pdf,application/pdf"
                    required
                    disabled={!editable}
                    onChange={(e) => setFile(e.target.files?.[0] || null)}
                  />
                </label>
              )}
              <div className="form-columns">
                {[
                  ["year", "سنة الحل"],
                  ["session", "دورة الحل"],
                  ["exam_type", "نوع امتحان الحل"],
                ].map(([key, label]) => (
                  <label key={key}>
                    {label}
                    <input
                      value={(metadata as any)[key]}
                      required={["subject", "track"].includes(key)}
                      disabled={!editable}
                      onChange={(e) =>
                        setMetadata({ ...metadata, [key]: e.target.value })
                      }
                    />
                  </label>
                ))}
              </div>
              <label>
                مصدر الحل / دليل نسبته
                <input
                  required
                  disabled={!editable}
                  value={metadata.source}
                  onChange={(e) =>
                    setMetadata({ ...metadata, source: e.target.value })
                  }
                />
              </label>
              <label>
                وصف مصدر الحل
                <select
                  value={metadata.designation}
                  disabled={!editable}
                  onChange={(e) =>
                    setMetadata({ ...metadata, designation: e.target.value })
                  }
                >
                  <option value="provided">حل مرفق، غير مصنّف رسميًا</option>
                  <option value="official_source">
                    من مصدر رسمي — ادعاء المالك يتطلب دليلًا
                  </option>
                </select>
              </label>
              <button disabled={!editable || (!combined && !file)}>
                إرفاق الحل للمراجعة
              </button>
            </form>
          ) : (
            <>
              <div
                className={
                  solution.verification === "owner_verified"
                    ? "info"
                    : "warning"
                }
              >
                {solution.verification === "owner_verified"
                  ? "المطابقة مؤكدة من المالك؛ ليست شهادة تلقائية برسمية الحل."
                  : "لن تُعتمد هذه النسخة قبل التحقق من مطابقة الحل ومصدره."}
              </div>
              {solution.verification !== "owner_verified" && (
                <form
                  onSubmit={(e) => {
                    e.preventDefault();
                    action(async () => {
                      await api(path + "/solution/verify", "POST", {
                        matching_confirmed: matching,
                        source_confirmed: provenance,
                        evidence,
                      });
                      await refresh();
                    });
                  }}
                >
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={matching}
                      disabled={!editable}
                      onChange={(e) => setMatching(e.target.checked)}
                    />
                    قارنت الموضوع بالحل وأؤكد مطابقة المسائل والهوية
                  </label>
                  <label className="check">
                    <input
                      type="checkbox"
                      checked={provenance}
                      disabled={!editable}
                      onChange={(e) => setProvenance(e.target.checked)}
                    />
                    راجعت مصدر الحل ووصفه ولا أعتمد تشابه العنوان
                  </label>
                  <label>
                    دليل المطابقة
                    <textarea
                      required
                      minLength={20}
                      value={evidence}
                      disabled={!editable}
                      onChange={(e) => setEvidence(e.target.value)}
                    />
                  </label>
                  <button
                    disabled={
                      !editable ||
                      !matching ||
                      !provenance ||
                      evidence.trim().length < 20
                    }
                  >
                    تأكيد مطابقة الحل
                  </button>
                </form>
              )}
              <button
                disabled={!editable}
                onClick={() =>
                  action(async () => {
                    await api(path + "/solution", "DELETE");
                    await refresh();
                  })
                }
              >
                إزالة الحل من المسودة
              </button>
            </>
          )}
        </>
      )}
    </div>
  );
}
