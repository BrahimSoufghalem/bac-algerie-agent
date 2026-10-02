import React, { useEffect, useState, useRef, useId } from "react";
import { Icon } from "./ChatUI";
type API = (path: string, method?: string, body?: unknown) => Promise<any>;
type Props = {
  api: API;
  role: string;
  chat: string;
  notify: (s: string) => void;
  request: (s: string) => Promise<void>;
  render: (blocks: any[]) => React.ReactNode;
};
function download(data: any, name: string) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function useAction(notify: (s: string) => void) {
  const [busy, setBusy] = useState(false);
  return {
    busy,
    go: async (fn: () => Promise<void>) => {
      setBusy(true);
      try {
        await fn();
      } catch (e) {
        notify((e as Error).message);
      } finally {
        setBusy(false);
      }
    },
  };
}
export function PreferencesPanel({ api, chat, notify, role }: Props) {
  const [p, setP] = useState<any>(null),
    [subjectText, setSubjectText] = useState(""),
    [scope, setScope] = useState("global"),
    [password, setPassword] = useState("");
  const { go, busy } = useAction(notify);
  useEffect(() => {
    go(async () => {
      const pref = await api("/api/preferences");
      setP(pref);
      setSubjectText(pref.subjects.join(", "));
    });
  }, []);
  if (!p) return <p>جارٍ تحميل الإعدادات…</p>;
  return (
    <section className="page-content">
      <h1>تفضيلات التعلّم والخصوصية</h1>
      <p>
        التفضيلات سياق للشرح، لا تغيّر الصلاحيات. تغييرها يوقف التشغيل الجاري؛
        لا يمكن سحب بيانات أُرسلت بالفعل للمزوّد.
      </p>
      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault();
          go(async () => {
            await api(
              scope === "chat"
                ? `/api/conversations/${chat}/preferences`
                : "/api/preferences",
              scope === "chat" ? "PUT" : "PUT",
              {
                ...p,
                subjects: subjectText
                  .split(",")
                  .map((x) => x.trim())
                  .filter(Boolean),
              },
            );
            notify("حُفظت التفضيلات");
          });
        }}
      >
        <label>
          نطاق التفضيلات
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="global">الحساب</option>
            {chat && <option value="chat">هذه المحادثة فقط</option>}
          </select>
        </label>
        <label>
          الشعبة
          <input
            value={p.track}
            maxLength={100}
            onChange={(e) => setP({ ...p, track: e.target.value })}
          />
        </label>
        <label>
          المواد (فاصلة بين المواد)
          <input
            value={subjectText}
            onChange={(e) => setSubjectText(e.target.value)}
          />
        </label>
        <label>
          لغة الشرح
          <select
            value={p.language}
            onChange={(e) => setP({ ...p, language: e.target.value })}
          >
            <option value="ar">العربية</option>
            <option value="fr">Français</option>
            <option value="en">English</option>
          </select>
        </label>
        <label>
          تفصيل الشرح
          <select
            value={p.detail}
            onChange={(e) => setP({ ...p, detail: e.target.value })}
          >
            <option value="brief">مختصر</option>
            <option value="balanced">متوازن</option>
            <option value="deep">تفصيلي</option>
          </select>
        </label>
        <label>
          طريقة الشرح
          <select
            value={p.style}
            onChange={(e) => setP({ ...p, style: e.target.value })}
          >
            <option value="guided">تدريجي</option>
            <option value="direct">مباشر</option>
          </select>
        </label>

        <button className="primary" disabled={busy}>
          حفظ التفضيلات
        </button>
        {scope === "chat" && (
          <button
            type="button"
            onClick={() =>
              go(async () => {
                await api(`/api/conversations/${chat}/preferences`, "PUT", {});
                notify("عادت المحادثة إلى تفضيلات الحساب");
              })
            }
          >
            إزالة تجاوزات المحادثة
          </button>
        )}
      </form>
      <div className="panel">
        <h2>بياناتي الخاصة</h2>
        <button
          onClick={() =>
            go(async () =>
              download(
                await api("/api/privacy/export"),
                "masar-personal-export.json",
              ),
            )
          }
        >
          تصدير بياناتي JSON
        </button>
        <p>
          لا يحتوي التصدير على مفاتيح المزوّد أو الجلسات. الملفات المؤقتة تُحمّل
          منفصلة قبل انتهاء صلاحيتها.
        </p>
        {role !== "owner" && (
          <>
            <label>
              كلمة المرور لتأكيد حذف الحساب
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </label>
            <button
              disabled={busy || !password}
              onClick={() => {
                if (
                  confirm(
                    "حذف حسابك ومحادثاتك وملاحظاتك وملفاتك الخاصة نهائيًا؟",
                  )
                )
                  go(async () => {
                    await api("/api/privacy/account", "DELETE", {
                      password,
                      confirm: true,
                    });
                    location.reload();
                  });
              }}
            >
              حذف حسابي وبياناتي
            </button>
          </>
        )}
      </div>
    </section>
  );
}
export function NotesPanel({ api, notify }: Props) {
  const [rows, setRows] = useState<any[]>([]);
  const { go } = useAction(notify);
  useEffect(() => {
    go(async () => setRows((await api("/api/notes")).items));
  }, []);
  const labels: any = {
    goal: "هدف",
    weakness: "صعوبة",
    mistake: "خطأ متكرر",
    mastered: "إتقان",
  };
  return (
    <section className="page-content">
      <h1>ملاحظات مسار التعليمية</h1>
      <p>
        يكتب مسار هذه الملاحظات ويحدّثها وفق تقدّمك في التعلّم. هي ملاحظات
        تعليمية قابلة للمراجعة، وليست تقييمًا دائمًا لشخصك. للقراءة فقط.
      </p>
      {!rows.length && <p className="muted">لا توجد ملاحظات تعليمية بعد.</p>}
      {rows.map((n) => (
        <article className="panel" key={n.id}>
          <strong>{labels[n.category] || "ملاحظة"}</strong>
          <p>{n.content}</p>
        </article>
      ))}
    </section>
  );
}
export function PrivateUploads({
  api,
  chat,
  notify,
  ensureChat,
}: {
  api: API;
  chat: string;
  notify: (s: string) => void;
  ensureChat: () => Promise<string | undefined>;
}) {
  const [rows, setRows] = useState<any[]>([]);
  const [open, setOpen] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [transferring, setTransferring] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const currentChat = useRef(chat);
  currentChat.current = chat;
  const id = useId();
  const { go, busy } = useAction(notify);
  const refresh = async (target = chat) => {
    const result = await api(`/api/conversations/${target}/uploads`);
    if (currentChat.current === target) setRows(result.items);
  };
  useEffect(() => {
    setRows([]);
    setError("");
    if (chat) go(() => refresh(chat));
  }, [chat]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        setDragging(false);
        container.current
          ?.querySelector<HTMLButtonElement>(".attachment-trigger")
          ?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);
  const upload = (file?: File) => {
    if (!file || busy) return;
    setError("");
    if (file.size > 10 * 1024 * 1024 || rows.length >= 5) {
      setError(
        file.size > 10 * 1024 * 1024
          ? "حجم الملف أكبر من 10 MB. اختر ملفًا أصغر."
          : "يمكن إرفاق خمسة ملفات. احذف ملفًا قبل إضافة آخر.",
      );
      return;
    }
    if (!/\.(pdf|png|jpe?g|webp|txt)$/i.test(file.name)) {
      setError("اختر ملف PDF أو صورة PNG/JPG/WebP أو نص TXT.");
      return;
    }
    setTransferring(true);
    go(async () => {
      try {
        const target = currentChat.current || (await ensureChat());
        if (!target) return;
        const data = new FormData();
        data.set("file", file);
        await api(`/api/conversations/${target}/upload`, "POST", data);
        await refresh(target);
      } catch (failure) {
        setError((failure as Error).message);
        throw failure;
      } finally {
        setTransferring(false);
      }
    });
  };
  return (
    <div className="private-files" ref={container}>
      <button
        type="button"
        className="attachment-trigger"
        aria-label="إرفاق ملف خاص مؤقتًا · 24 ساعة"
        title="إرفاق ملف"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen(!open)}
      >
        <Icon name="attach" />
        <span className="attachment-count">{rows.length || ""}</span>
      </button>
      <div
        id={id}
        className={"attachment-panel " + (open ? "is-open" : "")}
        aria-label="إرفاق الملفات"
        role="region"
        aria-hidden={!open}
        inert={!open}
      >
        <div className="attachment-heading">
          <span className="attachment-heading-icon">
            <Icon name="attach" size={19} />
          </span>
          <div>
            <strong>أضف سياقًا لسؤالك</strong>
            <small>ملفاتك هنا خاصة ومؤقتة</small>
          </div>
          <button
            type="button"
            className="icon-button"
            aria-label="إغلاق الإرفاق"
            onClick={() => {
              setOpen(false);
              container.current
                ?.querySelector<HTMLButtonElement>(".attachment-trigger")
                ?.focus();
            }}
          >
            <Icon name="close" size={17} />
          </button>
        </div>
        <input
          id={id + "-file"}
          ref={input}
          className="attachment-input"
          type="file"
          aria-label="الملف الخاص"
          tabIndex={-1}
          accept=".pdf,.png,.jpg,.jpeg,.webp,.txt"
          disabled={busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            upload(file);
          }}
        />
        <button
          type="button"
          className={"attachment-dropzone " + (dragging ? "is-dragging" : "")}
          disabled={busy}
          onClick={() => input.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            upload(event.dataTransfer.files[0]);
          }}
        >
          <span className="dropzone-icon">
            <Icon name={transferring ? "retry" : "plus"} size={23} />
          </span>
          <strong>
            {transferring ? "جارٍ رفع الملف…" : "اختر ملفًا أو اسحبه هنا"}
          </strong>
          <span>PDF · صور · TXT</span>
          <small>حتى 10 MB للملف · 20 صفحة للـPDF</small>
        </button>
        {error && (
          <p className="attachment-error" role="alert">
            {error}
          </p>
        )}
        {rows.length > 0 && (
          <div className="attachment-list-heading">
            المرفقات <span>{rows.length}/5</span>
          </div>
        )}
        <div className="attachment-file-list">
          {rows.map((file) => (
            <div className="private-file-row" key={file.id}>
              <span className="file-type-mark">
                <Icon name="note" size={19} />
              </span>
              <div className="attachment-file-info">
                <strong title={file.name}>{file.name}</strong>
                <small>{file.pages} صفحة · محفوظ لمدة 24 ساعة</small>
              </div>
              <a
                href={`/api/private/${file.id}/original`}
                className="file-action"
                aria-label={"تحميل " + file.name}
                title="تحميل ملفك"
              >
                <Icon name="down" size={16} />
              </a>
              <button
                type="button"
                className="file-action"
                aria-label={"حذف الملف " + file.name}
                title="حذف الملف"
                disabled={busy}
                onClick={() =>
                  go(async () => {
                    await api("/api/private/" + file.id, "DELETE");
                    await refresh();
                  })
                }
              >
                <Icon name="trash" size={16} />
              </button>
            </div>
          ))}
        </div>
        <p className="attachment-privacy">
          <Icon name="shield" size={14} />
          <span>
            لا يُنشر الملف أو يُضاف إلى مراجع مشتركة. رفعه لا يرسل سؤالًا.
          </span>
        </p>
        <p className="attachment-cost">
          قد تُحتسب قراءة المحتوى عند إرسال سؤالك. تُحذف الملفات المؤقتة بعد
          انتهاء صلاحيتها.
        </p>
        {transferring && (
          <span className="attachment-upload-status" role="status">
            جارٍ رفع الملف…
          </span>
        )}
      </div>
    </div>
  );
}
export function MaterialsPanel({ api, role, notify, request, render }: Props) {
  const [rows, setRows] = useState<any[]>([]),
    [selected, setSelected] = useState<any>(null),
    [kind, setKind] = useState("lesson_plan"),
    [topic, setTopic] = useState(""),
    [level, setLevel] = useState("الثالثة ثانوي"),
    [difficulty, setDifficulty] = useState("متوسط");
  const { go, busy } = useAction(notify);
  const refresh = async () => setRows((await api("/api/materials")).items);
  useEffect(() => {
    go(refresh);
  }, []);
  const labels: any = {
    lesson_plan: "خطة درس وعرض",
    exercise_set: "تمارين متدرجة",
    exam: "اختبار كامل مع حل وسلم",
    grading: "تصحيح وإبداء ملاحظات",
    reference_review: "مراجعة شرح أو مرجع",
  };
  return (
    <section className="page-content">
      <h1>مساحة إعداد الأستاذ</h1>
      <p>
        محرك واحد، وأدوات بحسب الدور. المخرجات مسودات خاصة مولّدة، ليست حلولًا
        رسمية. راجعها قبل استعمالها.
      </p>
      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault();
          go(async () =>
            request(
              `مهمة تعليمية: ${labels[kind]}. الموضوع/المعطيات: ${topic}. المستوى: ${level}. الصعوبة: ${difficulty}. قدّم محتوى تعليميًا مناسبًا مع الحسابات اللازمة، وحل منفصل وسلم متسق عند الحاجة. احفظه مسودة تعليمية، لا حلًا رسميًا. إذا كانت بيانات التصحيح غير كافية اسأل بدل اختراع العلامة.`,
            ),
          );
        }}
      >
        <label>
          المهمة
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            {Object.entries(labels)

              .map(([k, v]) => (
                <option key={k} value={k}>
                  {String(v)}
                </option>
              ))}
          </select>
        </label>
        <label>
          الموضوع أو إجابة الطالب التي لديك
          <textarea
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            required
            maxLength={3000}
          />
        </label>
        <label>
          المستوى
          <input
            value={level}
            maxLength={100}
            onChange={(e) => setLevel(e.target.value)}
          />
        </label>
        <label>
          الصعوبة
          <select
            value={difficulty}
            onChange={(e) => setDifficulty(e.target.value)}
          >
            <option>بسيط</option>
            <option>متوسط</option>
            <option>متقدم</option>
          </select>
        </label>
        <p>
          عند الضغط يُرسل طلب إلى النموذج المحفوظ وقد يستهلك رصيدًا. لا يستطيع
          الأستاذ قراءة محادثات الطلاب أو ملاحظاتهم.
        </p>
        <button className="primary" disabled={busy}>
          بدء إعداد مسودة
        </button>
      </form>
      <button onClick={() => go(refresh)}>تحديث المسودات</button>
      {rows.map((m) => (
        <article key={m.id} className="panel">
          <strong>
            {m.title} · {labels[m.kind]}
          </strong>
          <p>مولّد · خاص · غير رسمي</p>
          <button onClick={() => setSelected(m)}>عرض المسودة</button>
          <button onClick={() => download(m, "masar-material.json")}>
            تصدير المسودة
          </button>
          <button
            onClick={() =>
              go(async () => {
                await api("/api/materials/" + m.id, "DELETE");
                if (selected?.id === m.id) setSelected(null);
                await refresh();
              })
            }
          >
            حذف المسودة
          </button>
        </article>
      ))}
      {selected && (
        <article className="panel">
          <h2>{selected.title}</h2>
          {render(selected.payload.blocks)}
          {selected.payload.warnings?.map((w: string, i: number) => (
            <p className="warning" key={i}>
              {w}
            </p>
          ))}
          {selected.payload.rubric?.length > 0 && (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>معيار</th>
                    <th>الحد</th>
                    <th>الممنوح</th>
                    <th>ملاحظات</th>
                  </tr>
                </thead>
                <tbody>
                  {selected.payload.rubric.map((c: any, i: number) => (
                    <tr key={i}>
                      <td>{c.title}</td>
                      <td>{c.maximum}</td>
                      <td>{c.awarded ?? "—"}</td>
                      <td>{c.feedback}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {selected.payload.solution && (
            <details>
              <summary>الحل المنفصل — مولّد، راجعه</summary>
              <pre className="material-solution" dir="auto">
                {selected.payload.solution}
              </pre>
            </details>
          )}
        </article>
      )}
    </section>
  );
}
export function AccountsPanel({ api, notify }: Props) {
  const [rows, setRows] = useState<any[]>([]),
    [q, setQ] = useState(""),
    [offset, setOffset] = useState(0),
    [audit, setAudit] = useState<any[]>([]);
  const { go, busy } = useAction(notify);
  const refresh = async (off = offset) =>
    setRows(
      (
        await api(
          "/api/owner/accounts?q=" + encodeURIComponent(q) + "&offset=" + off,
        )
      ).items,
    );
  useEffect(() => {
    go(() => refresh());
  }, []);
  return (
    <section className="page-content">
      <h1>الحسابات والحدود</h1>
      <button
        onClick={() =>
          go(async () => setAudit((await api("/api/owner/audit")).items))
        }
      >
        عرض سجل الإدارة
      </button>
      {audit.length > 0 && (
        <details open>
          <summary>أحداث إدارية بلا مفاتيح أو كلمات مرور</summary>
          <pre className="material-solution" dir="ltr">
            {JSON.stringify(audit, null, 2)}
          </pre>
        </details>
      )}
      <p>
        إدارة الدور والحدود فقط، لا تعرض محادثات المستخدم أو ملاحظاته. تغيير
        الدور يلغي جلساته ويوقف تشغيله الجاري. الحد الرمزي مراقبة للرموز المبلّغ
        عنها، لا ضمان لفاتورة نهائية.
      </p>
      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          const form = e.currentTarget;
          go(async () => {
            await api("/api/owner/accounts", "POST", Object.fromEntries(f));
            form.reset();
            await refresh();
          });
        }}
      >
        <h2>إضافة حساب أستاذ أو طالب</h2>
        <label>
          اسم الحساب
          <input name="name" required maxLength={100} />
        </label>
        <label>
          بريد الحساب
          <input name="email" type="email" required />
        </label>
        <label>
          كلمة المرور الأولية
          <input
            name="password"
            type="password"
            autoComplete="new-password"
            minLength={12}
            required
          />
        </label>
        <label>
          الدور الجديد
          <select name="role">
            <option value="teacher">أستاذ</option>
            <option value="student">طالب</option>
          </select>
        </label>
        <button className="primary" disabled={busy}>
          إنشاء الحساب
        </button>
      </form>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          setOffset(0);
          go(() => refresh(0));
        }}
      >
        <label>
          البحث عن حساب
          <input value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <button>بحث الحسابات</button>
      </form>
      {rows.map((u) => (
        <form
          className="panel"
          key={u.id}
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            const body: any = {
              role: f.get("role"),
              active: f.get("active") === "on",
            };
            for (const k of ["daily_limit", "daily_tokens", "budget_alert"])
              body[k] = f.get(k) === "" ? null : Number(f.get(k));
            for (const k of ["messages_per_minute", "max_active_runs"])
              body[k] = Number(f.get(k));
            go(async () => {
              await api("/api/owner/accounts/" + u.id, "PATCH", body);
              await refresh();
              notify("حُفظت حدود الحساب");
            });
          }}
        >
          <h2>{u.name}</h2>
          <p dir="ltr">{u.email}</p>
          <label>
            دور الحساب
            <select name="role" defaultValue={u.role}>
              <option value="student">طالب</option>
              <option value="teacher">أستاذ</option>
              <option value="owner">مالك</option>
            </select>
          </label>
          <label className="check">
            <input name="active" type="checkbox" defaultChecked={!!u.active} />
            حساب نشط
          </label>
          {[
            ["daily_limit", "تشغيلات يومية (0 يمنع التشغيل)"],
            ["daily_tokens", "حد الرموز المبلّغ عنها / 24 ساعة"],
            ["budget_alert", "تنبيه تكلفة / 24 ساعة"],
            ["messages_per_minute", "رسائل في الدقيقة"],
            ["max_active_runs", "تشغيلات متزامنة"],
          ].map(([k, l]) => (
            <label key={k}>
              {l}
              <input
                name={k}
                type="number"
                min={
                  ["messages_per_minute", "max_active_runs"].includes(k) ? 1 : 0
                }
                step={k === "budget_alert" ? "any" : 1}
                defaultValue={u[k] ?? ""}
              />
            </label>
          ))}
          <button disabled={busy}>حفظ حدود {u.name}</button>
        </form>
      ))}
      <button
        disabled={!offset}
        onClick={() => {
          const n = Math.max(0, offset - 50);
          setOffset(n);
          go(() => refresh(n));
        }}
      >
        السابقة
      </button>
      <button
        disabled={rows.length < 50}
        onClick={() => {
          setOffset(offset + 50);
          go(() => refresh(offset + 50));
        }}
      >
        التالية
      </button>
    </section>
  );
}
export function PersonalUsage({ api, notify }: Props) {
  const [data, setData] = useState<any>(null);
  useEffect(() => {
    api("/api/usage")
      .then(setData)
      .catch((e) => notify(e.message));
  }, []);
  return (
    <section className="page-content">
      <h1>استخدامي وحدودي</h1>
      <p>
        المعلومات التي يبلّغ عنها المزوّد فقط. غير المتاح لا يعني صفرًا. قد
        يتجاوز طلب جارٍ حد الرموز قبل أن يعيد المزوّد أرقامه.
      </p>
      {data?.budget_alert_reached && (
        <p className="warning">
          وصلت التكلفة المقدرة إلى عتبة التنبيه التي حددها المالك.
        </p>
      )}
      {data?.budget_unknown && (
        <p className="warning">
          بعض الاستخدامات بلا تكلفة متاحة؛ التنبيه ليس ضمانًا لفاتورة نهائية.
        </p>
      )}
      <pre className="material-solution" dir="ltr">
        {data ? JSON.stringify(data, null, 2) : "جارٍ التحميل…"}
      </pre>
    </section>
  );
}
