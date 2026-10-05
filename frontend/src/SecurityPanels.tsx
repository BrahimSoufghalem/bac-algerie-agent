import { Input } from "./components/ui/input";
import { NativeSelect } from "./components/ui/native-select";
import { Button } from "./components/ui/button";
import { Card } from "./components/ui/card";
import React, { useEffect, useState } from "react";
type API = (p: string, m?: string, b?: unknown) => Promise<any>;
export function Recovery({
  api,
  link,
  back,
}: {
  api: API;
  link: string;
  back: () => void;
}) {
  const [policy, setPolicy] = useState<any>(null),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [purpose, token] = link.split(":");
  useEffect(() => {
    api("/api/auth/policy")
      .then(setPolicy)
      .catch(() => setNotice("تعذر فحص خدمة البريد"));
  }, []);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setNotice("");
    try {
      if (token) {
        await api(
          "/api/auth/" + (purpose === "verify" ? "verify" : "reset"),
          "POST",
          {
            token,
            ...(purpose === "verify" ? {} : { password: f.get("password") }),
          },
        );
        setNotice("تم تحديث الحساب. يمكنك العودة لتسجيل الدخول.");
      } else {
        await api(
          "/api/auth/" +
            (f.get("purpose") === "verify"
              ? "request-verification"
              : "request-reset"),
          "POST",
          { email: f.get("email") },
        );
        setNotice(
          "إن كان الحساب مؤهلًا والبريد مهيّأ، ستصلك رسالة. لا نكشف وجود الحساب.",
        );
      }
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="auth-page">
      <section className="auth-intro">
        <div className="logo">مَسار</div>
        <h1>وصول آمن لحسابك.</h1>
        <p>الرابط لمرة واحدة وينتهي خلال 20 دقيقة. لا تشارك الرابط مع أحد.</p>
      </section>
      <form className="auth-form" onSubmit={submit}>
        <h2>
          {token
            ? purpose === "verify"
              ? "تأكيد البريد"
              : "كلمة مرور جديدة"
            : "استعادة الحساب"}
        </h2>
        {!token ? (
          <>
            <label>
              البريد الإلكتروني
              <Input
                name="email"
                type="email"
                dir="ltr"
                required
                autoComplete="email"
              />
            </label>
            <label>
              نوع الطلب
              <NativeSelect name="purpose">
                <option value="reset">استعادة كلمة المرور</option>
                <option value="verify">إعادة إرسال تأكيد البريد</option>
              </NativeSelect>
            </label>
            {policy && !policy.mail_configured && (
              <p role="status">
                خدمة البريد غير مهيأة. تواصل مع مشغّل المنصة؛ لا تُرسل رسائل
                حاليًا.
              </p>
            )}
          </>
        ) : (
          purpose !== "verify" && (
            <label>
              كلمة المرور الجديدة
              <Input
                name="password"
                type="password"
                minLength={12}
                maxLength={256}
                autoComplete="new-password"
                required
              />
            </label>
          )
        )}
        {notice && <p role="status">{notice}</p>}
        <Button
          variant="outline"
          className="primary"
          disabled={busy || (!token && policy && !policy.mail_configured)}
        >
          {" "}
          {token ? "تأكيد التحديث" : "إرسال الرابط"}{" "}
        </Button>
        <Button variant="outline" type="button" onClick={back}>
          العودة للدخول
        </Button>
      </form>
    </main>
  );
}
export function SecurityPanel({
  api,
  notify,
}: {
  api: API;
  notify: (s: string) => void;
}) {
  const [busy, setBusy] = useState(false),
    [confirmed, setConfirmed] = useState(false);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const leave = () => {
    location.assign("/");
    location.reload();
  };
  return (
    <section tabIndex={0} className="page-content">
      <h1>أمان الحساب</h1>
      <p>
        تغيير كلمة المرور أو إلغاء الجلسات يوقف التشغيلات الجارية ويلغي رموز
        الخدمة التي أصدرتها. ستحتاج إلى تسجيل الدخول مجددًا.
      </p>
      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          action(async () => {
            await api("/api/auth/change-password", "POST", {
              current_password: f.get("current"),
              new_password: f.get("new"),
            });
            leave();
          });
        }}
      >
        <h2>تغيير كلمة المرور</h2>
        <label>
          كلمة المرور الحالية
          <Input
            name="current"
            type="password"
            autoComplete="current-password"
            maxLength={256}
            required
          />
        </label>
        <label>
          كلمة المرور الجديدة
          <Input
            name="new"
            type="password"
            minLength={12}
            maxLength={256}
            autoComplete="new-password"
            required
          />
        </label>
        <Button variant="outline" className="primary" disabled={busy}>
          تغيير وإلغاء الجلسات
        </Button>
      </form>
      <Card className="panel">
        <h2>إنهاء جميع الجلسات</h2>
        <label>
          <input
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          أوافق على تسجيل الخروج من جميع الأجهزة وإلغاء رموز الخدمة
        </label>
        <Button
          variant="outline"
          disabled={busy || !confirmed}
          onClick={() =>
            action(async () => {
              await api("/api/auth/revoke-sessions", "POST", {});
              leave();
            })
          }
        >
          إلغاء جميع الجلسات
        </Button>
      </Card>
    </section>
  );
}
export function ServiceTokens({
  api,
  notify,
}: {
  api: API;
  notify: (s: string) => void;
}) {
  const [docs, setDocs] = useState<any[]>([]),
    [items, setItems] = useState<any[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [secret, setSecret] = useState(""),
    [busy, setBusy] = useState(false);
  async function refresh() {
    setDocs((await api("/api/library/documents")).items);
    setItems((await api("/api/owner/service-tokens")).items);
  }
  useEffect(() => {
    refresh().catch((e) => notify(e.message));
  }, []);
  async function action(fn: () => Promise<void>) {
    setBusy(true);
    try {
      await fn();
      await refresh();
    } catch (e) {
      notify((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section tabIndex={0} className="page-content">
      <h1>وصول الوكلاء للمكتبة</h1>
      <p>
        قراءة فقط للكتب المنشورة المحددة؛ لا وصول للمحادثات أو الملفات الخاصة أو
        إعدادات النماذج. 60 طلبًا في الدقيقة لكل رمز.
      </p>
      <form
        className="panel"
        onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setSecret("");
          action(async () => {
            const r = await api("/api/owner/service-tokens", "POST", {
              label: f.get("label"),
              days: Number(f.get("days")),
              documents: selected,
            });
            setSecret(r.token);
          });
        }}
      >
        <label>
          اسم الوكيل
          <Input name="label" required maxLength={100} />
        </label>
        <label>
          صلاحية بالأيام
          <Input
            name="days"
            type="number"
            defaultValue={30}
            min={1}
            max={365}
            required
          />
        </label>
        <fieldset>
          <legend>الكتب المسموح بها</legend>
          {docs.map((d) => (
            <label key={d.id}>
              <input
                type="checkbox"
                checked={selected.includes(d.id)}
                onChange={(e) =>
                  setSelected(
                    e.target.checked
                      ? [...selected, d.id]
                      : selected.filter((x) => x !== d.id),
                  )
                }
              />
              {d.title}
            </label>
          ))}
          {!docs.length && (
            <p>انشر كتابًا أولًا؛ لا يمكن إصدار رمز شامل ضمنيًا.</p>
          )}
        </fieldset>
        <Button
          variant="outline"
          className="primary"
          disabled={busy || !selected.length}
        >
          إنشاء رمز قراءة
        </Button>
      </form>
      {secret && (
        <Card className="panel">
          <h2>انسخه الآن — لا يُعرض مرة أخرى</h2>
          <Input
            aria-label="رمز الخدمة الجديد"
            dir="ltr"
            readOnly
            value={secret}
            autoComplete="off"
          />
          <p>احفظه في خزنة أسرار وكيلك، لا في source code أو URL.</p>
          <Button
            variant="outline"
            onClick={() => {
              navigator.clipboard
                .writeText(secret)
                .then(() => notify("نُسخ الرمز"))
                .catch(() => notify("انسخ الحقل يدويًا"));
            }}
          >
            نسخ الرمز
          </Button>
          <Button variant="outline" onClick={() => setSecret("")}>
            إخفاء الرمز
          </Button>
        </Card>
      )}
      <h2>الرموز الصادرة</h2>
      {items.map((t) => (
        <article className="panel" key={t.id}>
          <strong>{t.label}</strong>
          <p>
            {t.revoked_at
              ? "ملغى"
              : t.expires_at * 1000 < Date.now()
                ? "منتهي"
                : "نشط"}{" "}
            · {t.documents.length} كتاب ·{" "}
            {new Date(t.expires_at * 1000).toLocaleDateString("ar")}
          </p>
          <Button
            variant="outline"
            disabled={busy || !!t.revoked_at}
            onClick={() =>
              action(async () => {
                await api("/api/owner/service-tokens/" + t.id, "DELETE");
                setSecret("");
              })
            }
          >
            إلغاء الرمز
          </Button>
        </article>
      ))}
      <h2>الاستدعاء</h2>
      <pre tabIndex={0} dir="ltr">
        {
          "Authorization: Bearer <SERVICE_TOKEN>\nGET /api/agent/books\nGET /api/agent/books/{book_id}/toc\nGET /api/agent/search?q=...\nGET /api/agent/get_lesson/{lesson_id}\nGET /api/agent/nodes/{lesson_id}/parts\nGET /api/agent/parts/{part_id}\nGET /api/agent/assets/{asset_id}"
        }
      </pre>
    </section>
  );
}
