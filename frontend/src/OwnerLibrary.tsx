import React, { useEffect, useState, useRef } from "react";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { Textarea } from "./components/ui/textarea";
import { NativeSelect } from "./components/ui/native-select";
import { Dialog, Icon } from "./ChatUI";
import { IdentityChoices, StudyCatalogue } from "./StudyChoices";
import "./ownerLibrary.css";

type Api = (path: string, method?: string, body?: unknown) => Promise<any>;
const TYPES = [
  { id: "textbook", label: "الدروس", kind: "book" },
  { id: "exercises", label: "التمارين", kind: "exercise_collection" },
  { id: "school_tests", label: "الفروض والاختبارات", kind: "exam" },
  { id: "bac_exams", label: "البكالوريا", kind: "exam" },
];
type Entry = {
  track: string;
  subject: string;
  subject_label: string;
  content: Record<
    string,
    { file_count: number; published_count: number; added: boolean }
  >;
};
const INITIAL = {
  title: "",
  kind: "book",
  content_type: "textbook",
  tracks: [] as string[],
  track: "",
  subject: "",
  source: "",
  year: "",
};

export default function OwnerLibrary({
  api,
  catalogue,
  notify,
  render,
}: {
  api: Api;
  catalogue: StudyCatalogue;
  notify: (text: string) => void;
  render: (text: string) => React.ReactNode;
}) {
  const [rows, setRows] = useState<Entry[]>([]);
  const [docs, setDocs] = useState<any[]>([]);
  const [track, setTrack] = useState(catalogue.tracks[0]?.id || "");
  const [meta, setMeta] = useState(INITIAL);
  const [uploadKey, setUploadKey] = useState(0);
  const [files, setFiles] = useState<File[]>([]);
  const [solution, setSolution] = useState<File | null>(null);
  const [matched, setMatched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<any>(null);
  const [ack, setAck] = useState(false);
  const [notes, setNotes] = useState("");
  const [deletion, setDeletion] = useState<any>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const deleteRequest = useRef(0);

  async function refresh() {
    const [inventory, documents] = await Promise.all([
      api("/api/owner/library/inventory"),
      api("/api/owner/documents"),
    ]);
    setRows(inventory.items);
    setDocs(documents.items);
  }
  useEffect(() => {
    refresh().catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (!track && catalogue.tracks.length) setTrack(catalogue.tracks[0].id);
  }, [catalogue.tracks.length]);
  async function work(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function openVersion(id: string) {
    const value = await api(`/api/owner/versions/${id}/preview`);
    setPreview(value);
    setAck(false);
    setNotes("");
  }
  async function upload(event: React.FormEvent) {
    event.preventDefault();
    if (!files.length) return;
    await work(async () => {
      const failures: string[] = [];
      let successes = 0;
      let last = "";
      for (const file of files) {
        const body = new FormData();
        body.append("file", file);
        body.append(
          "metadata",
          JSON.stringify({
            ...meta,
            title: files.length > 1 ? "" : meta.title,
          }),
        );
        if (
          solution &&
          files.length === 1 &&
          meta.content_type !== "textbook"
        ) {
          body.append("solution_file", solution);
          body.append(
            "package",
            JSON.stringify({ layout: "separate", matching_confirmed: matched }),
          );
        }
        try {
          const result = await api("/api/owner/documents/upload", "POST", body);
          successes++;
          last = result.version_id;
        } catch (e) {
          failures.push(`${file.name}: ${(e as Error).message}`);
        }
      }
      await refresh();
      if (last) await openVersion(last);
      notify(
        `استُورد ${successes} ملف. راجع المحتوى ثم انشره ليصبح متاحًا للطلاب.`,
      );
      if (failures.length) setError(failures.join("\n"));
      else {
        setFiles([]);
        setUploadKey((k) => k + 1);
        setSolution(null);
        setMatched(false);
      }
    });
  }
  function closeDeletion() {
    deleteRequest.current++;
    setDeletion(null);
    setConfirmed(false);
    setDeleteLoading(false);
  }
  async function deletePreview(request: any, documentId?: string) {
    const sequence = ++deleteRequest.current;
    setDeleteLoading(true);
    setConfirmed(false);
    // Reflect the NEW requested scope immediately; old tokens stay unusable
    // while refreshing. Cancel/another choice invalidates stale replies.
    setDeletion((old: any) =>
      old ? { ...old, request, confirmation_token: "" } : old,
    );
    try {
      const data = documentId
        ? await api(`/api/owner/documents/${documentId}/delete-preview`)
        : await api("/api/owner/library/remove-preview", "POST", request);
      if (sequence === deleteRequest.current)
        setDeletion({ ...data, request, documentId });
    } catch (e) {
      if (sequence === deleteRequest.current) {
        setError((e as Error).message);
        setDeletion(null);
      }
    } finally {
      if (sequence === deleteRequest.current) setDeleteLoading(false);
    }
  }
  const visible = rows.filter((row) => row.track === track);
  const selectedDocs = docs.filter((d) => d.tracks?.includes(track));
  const available = visible.filter((r) =>
    TYPES.some((t) => r.content[t.id].added),
  ).length;
  return (
    <section
      className="page-content markdown-library"
      tabIndex={0}
      aria-label="إدارة ملفات Markdown"
    >
      <header className="library-heading">
        <div>
          <p className="library-eyebrow">مكتبة مسار · إدارة المحتوى</p>
          <h1>ملفاتك، بوضوح.</h1>
          <p className="muted">
            ارفع Markdown جاهزًا، راجع محتواه، ثم انشره. لا استخراج صور ولا
            استدعاء نموذج أثناء الاستيراد.
          </p>
        </div>
        <span className="markdown-badge">.md</span>
      </header>
      {error && (
        <div role="alert" className="library-error">
          {error}
        </div>
      )}
      <section
        className="panel inventory-panel"
        aria-labelledby="inventory-heading"
      >
        <div className="library-section-heading">
          <div>
            <h2 id="inventory-heading">تغطية مواد الشعبة</h2>
            <p className="muted">
              كل المواد ظاهرة، بما فيها المواد التي لم تضف لها ملفات.
            </p>
          </div>
          <label>
            الشعبة
            <NativeSelect
              aria-label="الشعبة"
              value={track}
              onChange={(e) => setTrack(e.target.value)}
            >
              {catalogue.tracks.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </NativeSelect>
          </label>
        </div>
        <div className="inventory-summary">
          <span>
            <strong>{visible.length}</strong> مادة في الشعبة
          </span>
          <span>
            <strong>{available}</strong> مادة لها محتوى منشور
          </span>
          <span>
            <strong>{visible.length - available}</strong> مادة دون محتوى منشور
          </span>
        </div>
        <div
          className="inventory-scroll"
          tabIndex={0}
          aria-label="جدول تغطية المواد"
        >
          <table className="inventory-table">
            <thead>
              <tr>
                <th scope="col">المادة</th>
                {TYPES.map((t) => (
                  <th key={t.id} scope="col">
                    {t.label}
                  </th>
                ))}
                <th scope="col">إدارة</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((row) => (
                <tr key={row.subject}>
                  <th scope="row">{row.subject_label}</th>
                  {TYPES.map((t) => {
                    const value = row.content[t.id];
                    return (
                      <td key={t.id}>
                        <span
                          className={
                            value.added
                              ? "coverage-state ready"
                              : "coverage-state"
                          }
                        >
                          {value.added
                            ? "مضافة"
                            : value.file_count
                              ? "بانتظار النشر"
                              : "لم تُضف"}
                        </span>
                        <span className="coverage-count">
                          {value.file_count} ملفات
                          {value.file_count !== value.published_count
                            ? ` · ${value.published_count} منشور`
                            : ""}
                        </span>
                      </td>
                    );
                  })}
                  <td>
                    <Button
                      type="button"
                      variant="ghost"
                      disabled={
                        busy ||
                        deleteLoading ||
                        !TYPES.some((t) => row.content[t.id].file_count)
                      }
                      aria-label={`حذف محتوى ${row.subject_label}`}
                      onClick={() =>
                        deletePreview({
                          subject: row.subject,
                          track,
                          content_type: null,
                        })
                      }
                    >
                      <Icon name="trash" />
                      حذف المحتوى
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="library-footnote">
          الأعداد لملفات المصادر الحالية، لا لعدد الدروس أو المقاطع، ولا لنسخ
          المراجعة أو الحلول المرفقة. «مضافة» تعني وجود محتوى منشور.
        </p>
      </section>
      <div className="library-manage-grid">
        <form className="panel markdown-upload" onSubmit={upload}>
          <h2>إضافة ملفات</h2>
          <p className="muted">
            اختيارات المادة والشعب ونوع المحتوى تُطبّق على جميع الملفات المحددة.
          </p>
          <label className="file-drop">
            اختر ملفات Markdown
            <input
              key={uploadKey}
              type="file"
              accept=".md,text/markdown"
              multiple
              required
              onChange={(e) => {
                setFiles(Array.from(e.target.files || []));
                setSolution(null);
                setMatched(false);
              }}
            />
            <span>
              {files.length
                ? `${files.length} ملفات محددة`
                : "UTF-8 · امتداد .md"}
            </span>
          </label>
          {files.length > 0 && (
            <ul className="selected-filenames">
              {files.map((f, i) => (
                <li key={i}>{f.name}</li>
              ))}
            </ul>
          )}
          <label>
            نوع المحتوى
            <NativeSelect
              aria-label="نوع المحتوى"
              value={meta.content_type}
              onChange={(e) => {
                const t = TYPES.find((t) => t.id === e.target.value)!;
                setMeta({ ...meta, content_type: t.id, kind: t.kind });
                setSolution(null);
              }}
            >
              {TYPES.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.label}
                </option>
              ))}
            </NativeSelect>
          </label>
          <IdentityChoices
            catalogue={catalogue}
            value={meta}
            onChange={setMeta}
            disabled={busy}
          />
          <label>
            العنوان <span className="muted">(اختياري لملف واحد)</span>
            <Input
              value={meta.title}
              disabled={files.length > 1}
              onChange={(e) => setMeta({ ...meta, title: e.target.value })}
            />
          </label>
          <label>
            المصدر <span className="muted">(اختياري)</span>
            <Input
              value={meta.source}
              onChange={(e) => setMeta({ ...meta, source: e.target.value })}
            />
          </label>
          {(meta.content_type === "school_tests" ||
            meta.content_type === "bac_exams") && (
            <label>
              السنة{" "}
              <Input
                value={meta.year}
                onChange={(e) => setMeta({ ...meta, year: e.target.value })}
              />
            </label>
          )}
          {meta.content_type !== "textbook" && files.length === 1 && (
            <fieldset>
              <legend>
                حل مرفق <span className="muted">(اختياري)</span>
              </legend>
              <input
                aria-label="ملف الحل Markdown"
                type="file"
                accept=".md,text/markdown"
                onChange={(e) => {
                  setSolution(e.target.files?.[0] || null);
                  setMatched(false);
                }}
              />
              {solution && (
                <label className="library-check">
                  <input
                    type="checkbox"
                    checked={matched}
                    onChange={(e) => setMatched(e.target.checked)}
                  />
                  أؤكد أن الحل المرفق يطابق هذا الملف؛ ليس اعتمادًا علميًا
                  آليًا.
                </label>
              )}
            </fieldset>
          )}
          <p className="library-footnote">
            نستخدم كتل section_id وtitle وsummary وcovers الموجودة بعد المحتوى،
            سواء داخل سياج yaml أو بدونه.
          </p>
          <Button
            type="submit"
            disabled={
              busy ||
              !files.length ||
              !meta.subject ||
              !meta.tracks.length ||
              (!!solution && !matched)
            }
          >
            {busy ? "جارٍ الاستيراد…" : "استيراد الملفات"}
          </Button>
        </form>
        <section className="panel uploaded-files">
          <div className="library-section-heading">
            <h2>ملفات الشعبة</h2>
            <span className="muted">{selectedDocs.length} ملفات</span>
          </div>
          {!selectedDocs.length ? (
            <div className="library-empty">
              <Icon name="book" />
              <h3>لم تُضف ملفات بعد</h3>
              <p className="muted">
                ابدأ بملف Markdown؛ ستظهر حالته وعدده في الجدول.
              </p>
            </div>
          ) : (
            <ul>
              {selectedDocs.map((doc) => (
                <li key={doc.id}>
                  <div>
                    <strong>{doc.title}</strong>
                    <p className="muted">
                      {TYPES.find(
                        (t) =>
                          t.kind === doc.kind &&
                          (typeof doc.metadata === "string"
                            ? JSON.parse(doc.metadata).content_type
                            : doc.metadata.content_type) === t.id,
                      )?.label || doc.kind}{" "}
                      ·{" "}
                      {doc.published_version && doc.status === "ACTIVE"
                        ? "منشور"
                        : "غير منشور"}
                    </p>
                  </div>
                  <div className="library-file-actions">
                    <Button
                      type="button"
                      variant="outline"
                      disabled={busy}
                      onClick={() =>
                        work(() => openVersion(doc.versions[0].id))
                      }
                    >
                      معاينة
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      aria-label={`حذف الملف ${doc.title}`}
                      disabled={busy || deleteLoading}
                      onClick={() => deletePreview({}, doc.id)}
                    >
                      <Icon name="trash" />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
      {preview && (
        <section className="panel markdown-review" aria-label="معاينة الملف">
          <div className="library-section-heading">
            <div>
              <h2>معاينة قبل النشر</h2>
              <p className="muted">
                الملخصات للفهرسة؛ المحتوى أدناه هو النص الأصلي دون إعادة كتابة.
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              onClick={() => setPreview(null)}
            >
              إغلاق المعاينة
            </Button>
          </div>
          {preview.version.warnings.map((w: string, i: number) => (
            <p key={i} className="library-warning">
              {w}
            </p>
          ))}
          {preview.sections.map((s: any) => (
            <details key={s.id}>
              <summary>{s.title}</summary>
              <div className="routing-metadata">
                <strong>ملخص الراوتر</strong>
                <p>{s.metadata.summary}</p>
                <p>{s.metadata.covers?.join(" · ")}</p>
              </div>
              <div className="markdown-source">{render(s.content)}</div>
            </details>
          ))}
          {preview.version.status === "UPLOADED" && (
            <>
              <label className="library-check">
                <input
                  type="checkbox"
                  checked={ack}
                  onChange={(e) => setAck(e.target.checked)}
                />
                راجعت النص والتحذيرات وأوافق على اعتماده.
              </label>
              <label>
                ملاحظات المراجعة
                <Textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                />
              </label>
              <Button
                type="button"
                disabled={busy || !ack}
                onClick={() =>
                  work(async () => {
                    await api(
                      `/api/owner/versions/${preview.version.id}/review`,
                      "POST",
                      { acknowledge_issues: ack, notes },
                    );
                    await openVersion(preview.version.id);
                    await refresh();
                    notify("اعتُمد الملف؛ انشره ليصبح متاحًا للطلاب.");
                  })
                }
              >
                اعتماد المراجعة
              </Button>
            </>
          )}
          {preview.version.status === "REVIEWED" && (
            <Button
              type="button"
              disabled={busy}
              onClick={() =>
                work(async () => {
                  await api(
                    `/api/owner/versions/${preview.version.id}/publish`,
                    "POST",
                    {},
                  );
                  await openVersion(preview.version.id);
                  await refresh();
                  notify("نُشر المحتوى وأصبح متاحًا للراوتر والمجيب.");
                })
              }
            >
              نشر المحتوى
            </Button>
          )}
          {preview.version.status === "PUBLISHED" && (
            <p className="coverage-state ready">هذه النسخة منشورة</p>
          )}
        </section>
      )}
      {deletion && (
        <Dialog
          title={
            deletion.documentId ? "حذف ملف من المكتبة" : "حذف محتوى المادة"
          }
          close={() => {
            if (!busy) closeDeletion();
          }}
        >
          {error && (
            <p role="alert" className="library-error">
              {error}
            </p>
          )}
          <p>
            سيبقى اسم المادة في قائمة المواد. الحذف لا يمسح المحادثات السابقة،
            ولا النسخ الاحتياطية الموجودة خارج المكتبة.
          </p>
          {!deletion.documentId && (
            <>
              <label>
                نطاق الحذف
                <NativeSelect
                  aria-label="نطاق الحذف"
                  disabled={busy || deleteLoading}
                  value={deletion.request.track || "all"}
                  onChange={(e) =>
                    deletePreview({
                      ...deletion.request,
                      track: e.target.value === "all" ? null : e.target.value,
                    })
                  }
                >
                  <option value={track}>هذه الشعبة فقط</option>
                  <option value="all">المنصة كلها — جميع الشعب</option>
                </NativeSelect>
              </label>
              <label>
                نوع المحتوى
                <NativeSelect
                  aria-label="نوع المحتوى"
                  disabled={busy || deleteLoading}
                  value={deletion.request.content_type || "all"}
                  onChange={(e) =>
                    deletePreview({
                      ...deletion.request,
                      content_type:
                        e.target.value === "all" ? null : e.target.value,
                    })
                  }
                >
                  <option value="all">كل محتوى المادة</option>
                  {TYPES.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.label}
                    </option>
                  ))}
                </NativeSelect>
              </label>
            </>
          )}
          <p>
            <strong>{deletion.document_count} ملفات ضمن النطاق</strong>
            {deleteLoading ? " — جارٍ تحديث المعاينة…" : ""}
          </p>
          <ul className="deletion-file-list">
            {deletion.documents.map((d: any) => (
              <li key={d.id}>
                {d.title}
                {d.retained_in_other_tracks && (
                  <span className="muted"> — سيبقى لبقية الشعب</span>
                )}
              </li>
            ))}
          </ul>
          <label className="library-check">
            <input
              type="checkbox"
              checked={confirmed}
              disabled={busy || deleteLoading}
              onChange={(e) => setConfirmed(e.target.checked)}
            />
            أؤكد حذف المحتوى المحدد. لا يمكن التراجع عن حذف ملف غير مشترك.
          </label>
          <div className="library-dialog-actions">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={closeDeletion}
            >
              إلغاء
            </Button>
            <Button
              type="button"
              variant="destructive"
              disabled={
                busy || deleteLoading || !confirmed || !deletion.document_count
              }
              onClick={() =>
                work(async () => {
                  if (deletion.documentId)
                    await api(
                      `/api/owner/documents/${deletion.documentId}`,
                      "DELETE",
                      { confirmation_token: deletion.confirmation_token },
                    );
                  else
                    await api("/api/owner/library/remove", "POST", {
                      ...deletion.request,
                      confirmation_token: deletion.confirmation_token,
                    });
                  closeDeletion();
                  setPreview(null);
                  await refresh();
                  notify("حُذف المحتوى المحدد؛ أسماء المواد محفوظة.");
                })
              }
            >
              حذف المحتوى المحدد
            </Button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
