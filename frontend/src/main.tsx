import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import Markdown from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import "@fontsource/noto-sans-arabic/400.css";
import "@fontsource/noto-sans-arabic/600.css";
import "@fontsource/noto-sans-arabic/700.css";
import "./style.css";
import {
  PreferencesPanel,
  NotesPanel,
  PrivateUploads,
  MaterialsPanel,
  AccountsPanel,
  PersonalUsage,
} from "./LearningPanels";
import { Recovery, SecurityPanel, ServiceTokens } from "./SecurityPanels";
import BundleEditor from "./BundleEditor";
import {
  Verification,
  ScientificChart,
  ScientificDiagram,
  ScientificResult,
} from "./ScienceBlocks";
type User = { id: string; name: string; role: string };
type Source = {
  node_id: string;
  document_id: string;
  title: string;
  pages: number[];
  file_id?: string;
  source_id?: string;
  scope?: string;
  role?: string;
};
type Block = {
  type: string;
  text?: string;
  latex?: string;
  asset_id?: string;
  asset_url?: string;
  caption?: string;
  headers?: string[];
  rows?: string[][];
  language?: string;
  result_id?: string;
  result_ids?: string[];
  result?: ScientificResult;
};
type Message = {
  id: string;
  role: string;
  content: string;
  blocks: Block[];
  sources: Source[];
};
type Chat = { id: string; title: string };
let csrf = "";
async function api(path: string, method = "GET", body?: unknown) {
  const headers: Record<string, string> = { "X-CSRF-Token": csrf };
  if (body && !(body instanceof FormData))
    headers["Content-Type"] = "application/json";
  const res = await fetch(path, {
    method,
    credentials: "same-origin",
    headers,
    body: body
      ? body instanceof FormData
        ? body
        : JSON.stringify(body)
      : undefined,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || "تعذر تنفيذ الطلب");
  return data;
}
function Md({ text }: { text: string }) {
  return (
    <Markdown
      skipHtml
      remarkPlugins={[remarkMath, remarkGfm]}
      rehypePlugins={[[rehypeKatex, { trust: false, maxExpand: 1000 }]]}
      components={{
        a: ({ children, href }) => (
          <a href={href} target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        img: ({ src, alt }) =>
          typeof src === "string" && src.startsWith("/api/library/assets/") ? (
            <img src={src} alt={alt || "صورة المصدر"} loading="lazy" />
          ) : (
            <span className="muted">[صورة خارجية غير محمّلة]</span>
          ),
        td: ({ children }) => <td dir="auto">{children}</td>,
        th: ({ children }) => <th dir="auto">{children}</th>,
        table: ({ children }) => (
          <div className="table-scroll">
            <table>{children}</table>
          </div>
        ),
      }}
    >
      {text}
    </Markdown>
  );
}
function Content({ blocks }: { blocks: Block[] }) {
  return (
    <>
      {blocks.map((b, i) =>
        b.type === "text" ? (
          <Md key={i} text={b.text || ""} />
        ) : b.type === "equation" ? (
          <div key={i} className="equation" dir="ltr">
            <Md text={"$$\n" + b.latex + "\n$$"} />
            {b.result_ids?.map((id) => (
              <a
                className="equation-evidence"
                key={id}
                href={"/api/science/results/" + id}
                target="_blank"
                rel="noopener noreferrer"
              >
                مدخلات ونتيجة الفحص المرتبط
              </a>
            ))}
          </div>
        ) : b.type === "image" ? (
          <figure key={i}>
            <img
              src={
                b.asset_url?.startsWith("/api/private/")
                  ? b.asset_url
                  : "/api/library/assets/" + b.asset_id
              }
              alt={b.caption || "صورة من المصدر"}
            />
            <figcaption>{b.caption}</figcaption>
          </figure>
        ) : b.type === "table" ? (
          <div className="table-scroll" key={i}>
            <table>
              <thead>
                <tr>
                  {b.headers?.map((h, j) => (
                    <th dir="auto" key={j}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows?.map((r, j) => (
                  <tr key={j}>
                    {r.map((v, k) => (
                      <td dir="auto" key={k}>
                        {v}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : b.type === "verification" && b.result ? (
          <Verification key={i} result={b.result} />
        ) : b.type === "graph" && b.result ? (
          b.result.output.diagram ? (
            <ScientificDiagram key={i} result={b.result} />
          ) : (
            <ScientificChart key={i} result={b.result} />
          )
        ) : b.type === "code" ? (
          <pre dir="ltr" key={i}>
            <code>{b.text}</code>
          </pre>
        ) : null,
      )}
    </>
  );
}
function App() {
  const [recovery, setRecovery] = useState(() => {
    if (location.hash.startsWith("#auth=")) {
      const link = location.hash.slice(6);
      history.replaceState(null, "", location.pathname);
      return link;
    }
    return "";
  });
  useEffect(() => {
    const readLink = () => {
      if (location.hash.startsWith("#auth=")) {
        const link = location.hash.slice(6);
        history.replaceState(null, "", location.pathname);
        setRecovery(link);
      }
    };
    window.addEventListener("hashchange", readLink);
    return () => window.removeEventListener("hashchange", readLink);
  }, []);
  const [user, setUser] = useState<User | null>(null),
    [loading, setLoading] = useState(true),
    [authMode, setAuthMode] = useState("login"),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [view, setView] = useState("chat"),
    [menu, setMenu] = useState(false);
  const [chats, setChats] = useState<Chat[]>([]),
    [chatId, setChatId] = useState(""),
    [messages, setMessages] = useState<Message[]>([]),
    [query, setQuery] = useState(""),
    [text, setText] = useState(""),
    [editing, setEditing] = useState(""),
    [run, setRun] = useState(""),
    [delta, setDelta] = useState(""),
    [activities, setActivities] = useState<
      { id: number; label: string; success?: boolean }[]
    >([]),
    [warnings, setWarnings] = useState<string[]>([]),
    [source, setSource] = useState<any>(null);
  const stream = useRef<EventSource | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const [docs, setDocs] = useState<any[]>([]),
    [ownerDocs, setOwnerDocs] = useState<any[]>([]),
    [version, setVersion] = useState<any>(null),
    [reviewPage, setReviewPage] = useState<any>(null),
    [ack, setAck] = useState(false),
    [reviewNotes, setReviewNotes] = useState(""),
    [busy, setBusy] = useState(false);
  const [models, setModels] = useState<any[]>([]),
    [slot, setSlot] = useState("agent"),
    [model, setModel] = useState({
      base_url: "https://ohhmyagent.com/v1",
      model: "gpt-5.6-luna",
      temperature: 0.2,
      max_tokens: 4000,
      timeout: 90,
      output_mode: "json_object",
      input_price_per_million: null as number | null,
      output_price_per_million: null as number | null,
      cached_price_per_million: null as number | null,
    }),
    [key, setKey] = useState(""),
    [usage, setUsage] = useState<any>(null);
  const [uploadFile, setUploadFile] = useState<File | null>(null),
    [meta, setMeta] = useState({
      title: "",
      kind: "book",
      subject: "",
      track: "",
      year: "",
      session: "",
      exam_type: "",
      institution: "",
      source: "",
    });
  useEffect(() => {
    setAck(false);
    setReviewPage(null);
    setReviewNotes("");
  }, [version?.id]);
  const [filters, setFilters] = useState({
    kind: "",
    subject: "",
    track: "",
    year: "",
    session: "",
  });
  useEffect(() => {
    if (!source && !menu) return;
    const previous = document.activeElement as HTMLElement | null;
    const dialog = document.querySelector<HTMLElement>(
      source ? ".source-modal" : ".sidebar.open",
    );
    const controls = () =>
      [
        ...(dialog?.querySelectorAll<HTMLElement>(
          "button, a, input, summary",
        ) || []),
      ].filter(
        (element) =>
          element.offsetParent !== null && !element.hasAttribute("disabled"),
      );
    controls()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setSource(null);
        setMenu(false);
      }
      if (event.key === "Tab") {
        const items = controls();
        const first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [source, menu]);
  async function refreshChats() {
    const d = await api("/api/conversations?q=" + encodeURIComponent(query));
    setChats(d.items);
    return d.items as Chat[];
  }
  async function openChat(id: string) {
    stream.current?.close();
    setRun("");
    setDelta("");
    setActivities([]);
    setWarnings([]);
    const c = await api("/api/conversations/" + id);
    setChatId(id);
    location.hash = "chat=" + id;
    setMessages(c.messages);
    setEditing("");
    setView("chat");
    setMenu(false);
    if (c.active_run) subscribe(c.active_run.id);
  }
  function subscribe(id: string) {
    stream.current?.close();
    setRun(id);
    setDelta("");
    setActivities([]);
    const es = new EventSource("/api/runs/" + id + "/events");
    stream.current = es;
    const seen = new Set<number>();
    for (const kind of [
      "queued",
      "model_start",
      "tool_start",
      "tool_end",
      "delta",
      "answer",
      "error",
    ])
      es.addEventListener(kind, (event: Event) => {
        const e = event as MessageEvent;
        if (!e.data) return;
        const eid = Number(e.lastEventId);
        if (seen.has(eid)) return;
        seen.add(eid);
        const p = JSON.parse(e.data);
        if (kind === "delta") setDelta((x) => x + p.text);
        else if (kind === "answer") {
          setMessages((x) => [
            ...x.filter((m) => m.id !== p.message_id),
            {
              id: p.message_id,
              role: "assistant",
              content: "",
              blocks: p.blocks,
              sources: p.sources,
            },
          ]);
          setWarnings(p.warnings || []);
          setDelta("");
          setRun("");
          es.close();
          refreshChats().catch(() => {});
        } else if (kind === "error") {
          setNotice(p.label + " (" + p.code + ")");
          setRun("");
          es.close();
        } else
          setActivities((x) =>
            [...x, { id: eid, label: p.label, success: p.success }].slice(-12),
          );
      });
    es.onerror = () => {
      if (es.readyState !== EventSource.CLOSED)
        setNotice("انقطع اتصال البث؛ يحاول المتصفح استعادة الأحداث المحفوظة.");
    };
  }
  useEffect(() => {
    api("/api/auth/me")
      .then(async (d) => {
        if (d.verification_required) {
          setAuthMode("login");
          setError("راجع بريدك لتأكيد الحساب قبل الدخول.");
          return;
        }
        csrf = d.csrf;
        setUser(d.user);
        const list = await api("/api/conversations");
        setChats(list.items);
        const id = location.hash.startsWith("#chat=")
          ? location.hash.slice(6)
          : list.items[0]?.id;
        if (id) await openChat(id);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
    return () => stream.current?.close();
  }, []);
  useEffect(() => {
    if (user) {
      const t = setTimeout(() => refreshChats().catch(() => {}), 250);
      return () => clearTimeout(t);
    }
  }, [query, user?.id]);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [delta, messages.length]);
  useEffect(() => {
    if (
      !version ||
      view !== "owner-library" ||
      ["REVIEWED", "PUBLISHED"].includes(version.status)
    )
      return;
    const timer = setInterval(
      () =>
        api("/api/owner/versions/" + version.id)
          .then(setVersion)
          .catch(() => {}),
      2500,
    );
    return () => clearInterval(timer);
  }, [version?.id, version?.status, view]);
  async function authenticate(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setError("");
    try {
      const body: any = { email: f.get("email"), password: f.get("password") };
      if (authMode === "register") body.name = f.get("name");
      const d = await api("/api/auth/" + authMode, "POST", body);
      csrf = d.csrf;
      setUser(d.user);
      await refreshChats();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function createChat() {
    const c = await api("/api/conversations", "POST", {});
    await refreshChats();
    await openChat(c.id);
  }
  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    if (!text.trim() || run) return;
    setBusy(true);
    try {
      let id = chatId;
      if (!id) {
        const c = await api("/api/conversations", "POST", {
          title: text.slice(0, 65),
        });
        id = c.id;
        setChatId(id);
        location.hash = "chat=" + id;
      }
      const r = await api("/api/conversations/" + id + "/messages", "POST", {
        text,
        edit_message_id: editing || null,
      });
      const c = await api("/api/conversations/" + id);
      setMessages(c.messages);
      setText("");
      setEditing("");
      setNotice("");
      await refreshChats();
      subscribe(r.run_id);
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function navigate(next: string) {
    setView(next);
    setMenu(false);
    setSource(null);
    setNotice("");
    try {
      if (next === "library")
        setDocs((await api("/api/library/documents")).items);
      if (next === "owner-library")
        setOwnerDocs((await api("/api/owner/documents")).items);
      if (next === "models") {
        const items = (await api("/api/owner/models")).items;
        setModels(items);
        const m = items.find((x: any) => x.slot === slot);
        if (m) setModel(m);
      }
      if (next === "usage") setUsage(await api("/api/owner/usage"));
    } catch (e) {
      setNotice((e as Error).message);
    }
  }
  async function action(fn: () => Promise<any>) {
    setBusy(true);
    try {
      await fn();
    } catch (e) {
      setNotice((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function privateSource(src: Source) {
    await action(async () => {
      const path = `/api/private/${src.node_id}/pages/${src.pages[0]}`;
      const response = await fetch(path);
      if (!response.ok) throw new Error("انتهت صلاحية المصدر الخاص أو حُذف");
      if (response.headers.get("content-type")?.includes("application/json")) {
        const data = await response.json();
        setSource({ node: { title: src.title }, content: data.content });
      } else setSource({ node: { title: src.title }, private_image: path });
    });
  }
  async function requestMaterial(prompt: string) {
    const c = await api("/api/conversations", "POST", {
      title: "مسودة تعليمية",
    });
    await refreshChats();
    await openChat(c.id);
    const result = await api(`/api/conversations/${c.id}/messages`, "POST", {
      text: prompt,
    });
    const loaded = await api(`/api/conversations/${c.id}`);
    setMessages(loaded.messages);
    subscribe(result.run_id);
  }
  async function readSource(id: string) {
    await action(async () => {
      let payload = await api("/api/library/nodes/" + encodeURIComponent(id));
      if (["exam", "exercise_collection"].includes(payload.node.kind))
        payload = await api(
          "/api/library/nodes/" + encodeURIComponent(id) + "/bundle",
        );
      if (payload.node.kind === "lesson")
        payload.parts = (
          await api("/api/library/nodes/" + encodeURIComponent(id) + "/parts")
        ).items;
      setSource(payload);
    });
  }
  async function readPart(id: string) {
    await action(async () =>
      setSource(await api("/api/library/parts/" + encodeURIComponent(id))),
    );
  }
  async function refreshVersion() {
    setVersion(await api("/api/owner/versions/" + version.id));
    setOwnerDocs((await api("/api/owner/documents")).items);
  }
  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!uploadFile) return;
    await action(async () => {
      const f = new FormData();
      f.append("metadata", JSON.stringify(meta));
      f.append("file", uploadFile);
      const r = await api("/api/owner/documents/upload", "POST", f);
      setVersion(await api("/api/owner/versions/" + r.version_id));
      setOwnerDocs((await api("/api/owner/documents")).items);
      setNotice("حُفظت نسخة خام. عاين المصدر قبل بدء Vision؛ لم تُنشر للطلاب.");
    });
  }
  if (recovery)
    return (
      <Recovery
        api={api}
        link={recovery === "request" ? "" : recovery}
        back={() => setRecovery("")}
      />
    );
  if (loading) return <main className="loading">جارٍ فتح مسار…</main>;
  if (!user)
    return (
      <main className="auth-page">
        <div className="auth-intro">
          <div className="logo">
            مَسار<span>البكالوريا الجزائرية</span>
          </div>
          <h1>
            افهم الفكرة.
            <br />
            ثم ابنِ الحل.
          </h1>
          <p>
            مساحة تعلّم تجمع شرحًا تدريجيًا، ومصادر معتمدة، واستدعاء مباشر
            للدروس.
          </p>
          <div className="auth-note">
            مكتبة يراجعها المالك · مصادر وصفحات واضحة · بياناتك التعليمية خاصة
          </div>
        </div>
        <form className="auth-form" onSubmit={authenticate}>
          <h2>{authMode === "login" ? "مرحبًا بعودتك" : "ابدأ مسارك"}</h2>
          <p className="muted">
            {authMode === "login"
              ? "سجّل الدخول إلى مساحة التعلّم."
              : "الحساب الجديد طالب افتراضيًا؛ يعيّن المالك الأساتذة."}
          </p>
          {authMode === "register" && (
            <label>
              الاسم
              <input name="name" required autoComplete="name" />
            </label>
          )}
          <label>
            البريد الإلكتروني
            <input
              name="email"
              type="email"
              dir="ltr"
              required
              autoComplete="username"
            />
          </label>
          <label>
            كلمة المرور
            <input
              name="password"
              type="password"
              minLength={authMode === "register" ? 12 : undefined}
              required
              autoComplete={
                authMode === "login" ? "current-password" : "new-password"
              }
            />
          </label>
          {error && (
            <p role="alert" className="error">
              {error}
            </p>
          )}
          <button className="primary" type="submit">
            {authMode === "login" ? "دخول" : "إنشاء حساب"}
          </button>
          <button
            type="button"
            className="text-button"
            onClick={() => {
              setAuthMode(authMode === "login" ? "register" : "login");
              setError("");
            }}
          >
            {authMode === "login"
              ? "ليس لديك حساب؟ أنشئ حساب طالب"
              : "لديك حساب؟ سجّل الدخول"}
          </button>
          <button
            type="button"
            className="text-button"
            onClick={() => setRecovery("request")}
          >
            نسيت كلمة المرور أو تأكيد البريد؟
          </button>
        </form>
      </main>
    );
  return (
    <div className="app">
      {menu && (
        <div
          className="drawer-backdrop"
          aria-hidden="true"
          onClick={() => setMenu(false)}
        />
      )}
      <aside className={"sidebar " + (menu ? "open" : "")}>
        <div className="sidebar-top">
          <div className="logo">
            مَسار<span>وكيل البكالوريا</span>
          </div>
          <button
            className="drawer-close"
            aria-label="إغلاق القائمة"
            onClick={() => setMenu(false)}
          >
            ×
          </button>
        </div>
        <button className="new-chat" onClick={() => action(createChat)}>
          ＋ محادثة جديدة
        </button>
        <nav>
          <button
            className={view === "chat" ? "active" : ""}
            onClick={() => navigate("chat")}
          >
            ◌ المحادثة
          </button>
          <button
            className={view === "library" ? "active" : ""}
            onClick={() => navigate("library")}
          >
            ▤ المكتبة المنشورة
          </button>
          {user.role === "owner" && (
            <>
              <p className="nav-caption">إدارة المالك</p>
              <button
                className={view === "owner-library" ? "active" : ""}
                onClick={() => navigate("owner-library")}
              >
                ▥ إدارة المحتوى
              </button>
              <button
                className={view === "models" ? "active" : ""}
                onClick={() => navigate("models")}
              >
                ⚙ إعداد النماذج
              </button>
              <button
                className={view === "usage" ? "active" : ""}
                onClick={() => navigate("usage")}
              >
                ◷ الاستخدام
              </button>
            </>
          )}
        </nav>
        <nav className="learning-nav">
          <button onClick={() => navigate("security")}>أمان الحساب</button>
          {user.role === "owner" && (
            <button onClick={() => navigate("service-tokens")}>
              وصول الوكلاء
            </button>
          )}
          <button onClick={() => navigate("preferences")}>
            تفضيلات وخصوصية
          </button>
          <button onClick={() => navigate("notes")}>ملاحظاتي التعليمية</button>
          <button onClick={() => navigate("materials")}>
            {user.role === "student" ? "تدريبي الذاتي" : "مساحة إعداد الأستاذ"}
          </button>
          <button onClick={() => navigate("personal-usage")}>
            استخدامي وحدودي
          </button>
          {user.role === "owner" && (
            <button onClick={() => navigate("accounts")}>
              الحسابات والحدود
            </button>
          )}
        </nav>
        <label className="chat-search">
          <input
            placeholder="البحث في المحادثات"
            aria-label="البحث في المحادثات"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="chat-history">
          {chats.map((c) => (
            <div
              key={c.id}
              className={"history-item " + (c.id === chatId ? "selected" : "")}
            >
              <button onClick={() => action(() => openChat(c.id))}>
                {c.title}
              </button>
              <details>
                <summary aria-label="خيارات المحادثة">⋯</summary>
                <button
                  onClick={() => {
                    const title = prompt("عنوان المحادثة", c.title);
                    if (title)
                      action(async () => {
                        await api("/api/conversations/" + c.id, "PATCH", {
                          title,
                        });
                        await refreshChats();
                      });
                  }}
                >
                  إعادة تسمية
                </button>
                <button
                  onClick={() => {
                    if (confirm("حذف هذه المحادثة ورسائلها؟"))
                      action(async () => {
                        await api("/api/conversations/" + c.id, "DELETE");
                        if (chatId === c.id) {
                          setChatId("");
                          setMessages([]);
                          location.hash = "";
                        }
                        await refreshChats();
                      });
                  }}
                >
                  حذف
                </button>
              </details>
            </div>
          ))}
        </div>
        <div className="profile">
          <div>
            <strong>{user.name}</strong>
            <span>
              {user.role === "owner"
                ? "المالك"
                : user.role === "teacher"
                  ? "أستاذ"
                  : "طالب"}
            </span>
          </div>
          <button
            onClick={() =>
              action(async () => {
                await api("/api/auth/logout", "POST", {});
                stream.current?.close();
                setUser(null);
                setMessages([]);
                setChats([]);
                setChatId("");
                csrf = "";
              })
            }
          >
            خروج
          </button>
        </div>
      </aside>
      <div className="workspace">
        <header>
          <button
            className="menu-button"
            onClick={() => setMenu(!menu)}
            aria-label="فتح القائمة"
          >
            <svg
              aria-hidden="true"
              width="22"
              height="22"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
            >
              <path d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <strong>
            {[
              "security",
              "service-tokens",
              "preferences",
              "notes",
              "materials",
              "accounts",
              "personal-usage",
            ].includes(view)
              ? (
                  {
                    security: "أمان الحساب",
                    "service-tokens": "وصول الوكلاء",
                    preferences: "تفضيلات وخصوصية",
                    notes: "ملاحظاتي التعليمية",
                    materials: "المسودات التعليمية",
                    accounts: "الحسابات والحدود",
                    "personal-usage": "استخدامي وحدودي",
                  } as Record<string, string>
                )[view]
              : view === "chat"
                ? user.role === "teacher"
                  ? "مساحة الأستاذ"
                  : "محادثة تعليمية"
                : view === "library"
                  ? "المكتبة المنشورة"
                  : view === "owner-library"
                    ? "مراجعة المحتوى ونشره"
                    : view === "models"
                      ? "نماذج التدريس والاستخراج"
                      : "الاستخدام والمحاسبة"}
          </strong>
          <span className="header-note">مصادر واضحة · بلا خطوات وهمية</span>
        </header>
        {notice && (
          <div className="notice" role="status">
            {notice}
            <button onClick={() => setNotice("")} aria-label="إغلاق التنبيه">
              ×
            </button>
          </div>
        )}
        {view === "chat" ? (
          <>
            <section className="conversation">
              {!messages.length && !run ? (
                <div className="welcome">
                  <span className="eyebrow">التعلّم يبدأ بسؤال جيد</span>
                  <h1>
                    {user.role === "teacher"
                      ? "ما الذي نحضّره اليوم؟"
                      : "أين توقفتَ في الدرس؟"}
                  </h1>
                  <p>
                    اختر فكرة، أو اكتب المسألة كما وردت.
                    <br />
                    سأستخدم المصادر المنشورة عندما تكون متاحة، وأوضح ما لم أتمكن
                    من تأكيده.
                  </p>
                  <div className="starters">
                    {(user.role === "teacher"
                      ? [
                          "حضّر خطة درس اعتمادًا على المكتبة",
                          "أنشئ اختبارًا تدريبيًا غير رسمي مع سلم تصحيح",
                          "راجع شرحًا أعددته للطلاب",
                        ]
                      : [
                          "اشرح لي درسًا من المكتبة خطوة بخطوة",
                          "ساعدني على فهم خطئي في الحل",
                          "أريد تدريبًا على مفهوم لم أتقنه",
                        ]
                    ).map((x) => (
                      <button key={x} onClick={() => setText(x)}>
                        {x}
                        <span>←</span>
                      </button>
                    ))}
                  </div>
                  <p className="muted small">
                    المكتبة الخام لا تظهر هنا قبل مراجعتها ونشرها من المالك.
                  </p>
                </div>
              ) : (
                messages.map((m) => (
                  <article className={"message " + m.role} key={m.id}>
                    <div className="message-label">
                      {m.role === "user" ? "أنت" : "مسار"}
                      {m.role === "user" && !run && (
                        <button
                          className="text-button"
                          onClick={() => {
                            setEditing(m.id);
                            setText(m.content);
                          }}
                        >
                          تعديل
                        </button>
                      )}
                    </div>
                    <div className="message-body">
                      {m.blocks.length ? (
                        <Content blocks={m.blocks} />
                      ) : (
                        <Md text={m.content} />
                      )}
                    </div>
                    {m.sources.length > 0 && (
                      <div className="sources">
                        <span>المصادر</span>
                        {m.sources.map((src, i) => (
                          <button
                            key={i}
                            onClick={() =>
                              src.scope === "private"
                                ? privateSource(src)
                                : src.source_id?.includes(":part:")
                                  ? readPart(src.source_id)
                                  : readSource(src.node_id)
                            }
                          >
                            {src.title} · ص {src.pages.join("–")}
                          </button>
                        ))}
                      </div>
                    )}
                  </article>
                ))
              )}
              {activities.length > 0 && (
                <details className="activity" open={Boolean(run)}>
                  <summary>
                    {run ? "نشاط الوكيل الفعلي" : "الأدوات المستخدمة"}
                  </summary>
                  {activities.map((a) => (
                    <div
                      key={a.id}
                      className={a.success === false ? "error" : ""}
                    >
                      {a.success === true
                        ? "✓ "
                        : a.success === false
                          ? "! "
                          : "· "}
                      {a.label}
                    </div>
                  ))}
                </details>
              )}
              {delta && (
                <article className="message assistant">
                  <div className="message-label">مسار · بث مباشر</div>
                  <div className="message-body">
                    <Md text={delta} />
                  </div>
                </article>
              )}
              {warnings.map((w, i) => (
                <p className="warning" key={i}>
                  {w}
                </p>
              ))}
              <div ref={bottom} />
            </section>
            <div className="composer-wrap">
              {editing && (
                <div className="editing">
                  تعديل رسالة سابقة؛ ستُحفظ الردود التالية كنسخة غير نشطة.
                  <button
                    onClick={() => {
                      setEditing("");
                      setText("");
                    }}
                  >
                    إلغاء التعديل
                  </button>
                </div>
              )}
              <PrivateUploads api={api} chat={chatId} notify={setNotice} />
              <form className="composer" onSubmit={send}>
                <textarea
                  aria-label="رسالتك"
                  placeholder="اكتب سؤالك أو المسألة…"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  maxLength={8000}
                  rows={2}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                />
                <div className="composer-controls">
                  <span>Enter للإرسال · Shift + Enter لسطر جديد</span>
                  {run ? (
                    <button
                      type="button"
                      onClick={() =>
                        action(() =>
                          api("/api/runs/" + run + "/cancel", "POST", {}),
                        )
                      }
                    >
                      ■ إيقاف
                    </button>
                  ) : (
                    <button className="primary" disabled={busy || !text.trim()}>
                      إرسال ↑
                    </button>
                  )}
                </div>
              </form>
              {chatId && !run && messages.length > 0 && (
                <button
                  className="text-button retry"
                  onClick={() =>
                    action(async () => {
                      const d = await api(
                        "/api/conversations/" + chatId + "/retry",
                        "POST",
                        {},
                      );
                      const c = await api("/api/conversations/" + chatId);
                      setMessages(c.messages);
                      subscribe(d.run_id);
                    })
                  }
                >
                  إعادة محاولة الرسالة الأخيرة
                </button>
              )}
              <p className="composer-note">
                الإجابة قد تتضمن خطأ. راجع المصادر والتحذيرات، خصوصًا شروط
                المسائل والمعادلات.
              </p>
            </div>
          </>
        ) : null}
        {view === "library" && (
          <section className="page-content">
            <h1>مصادر جاهزة للتعلّم</h1>
            <p className="muted">
              تظهر فقط النسخ التي راجعها المالك ونشرها. الدروس بهيكلها الأصلي،
              والامتحانات والتمارين بحزمتها الكاملة.
            </p>
            <form
              className="library-filters"
              onSubmit={(e) => {
                e.preventDefault();
                action(async () => {
                  const q = new URLSearchParams(
                    Object.entries(filters).filter(([, v]) => v),
                  );
                  setDocs((await api("/api/library/documents?" + q)).items);
                });
              }}
            >
              <label>
                نوع المصدر
                <select
                  value={filters.kind}
                  onChange={(e) =>
                    setFilters({ ...filters, kind: e.target.value })
                  }
                >
                  <option value="">كل الأنواع</option>
                  <option value="book">كتاب</option>
                  <option value="exam">امتحان مع حلّه إن وجد</option>
                  <option value="exercise_collection">
                    سلسلة تمارين كاملة
                  </option>
                  <option value="reference">مرجع</option>
                </select>
              </label>
              {[
                ["subject", "تصفية المادة"],
                ["track", "تصفية التخصص"],
                ["year", "تصفية السنة"],
                ["session", "تصفية الدورة"],
              ].map(([k, label]) => (
                <label key={k}>
                  {label}
                  <input
                    value={(filters as any)[k]}
                    onChange={(e) =>
                      setFilters({ ...filters, [k]: e.target.value })
                    }
                  />
                </label>
              ))}
              <button>تطبيق التصفية</button>
            </form>
            {!docs.length ? (
              <div className="empty-state">
                لا توجد مصادر منشورة بعد. يستطيع المالك رفع كتاب ومراجعته من
                إدارة المحتوى.
              </div>
            ) : (
              docs.map((d) => (
                <div className="document-row" key={d.id}>
                  <div>
                    <h3>{d.title}</h3>
                    <p className="muted">
                      {d.subject} · {d.track} · {d.kind}{" "}
                      {d.year && " · " + d.year}{" "}
                      {d.metadata?.session && " · " + d.metadata.session}
                    </p>
                  </div>
                  <button
                    onClick={() =>
                      action(async () => {
                        const toc = await api(
                          "/api/library/documents/" + d.id + "/toc",
                        );
                        if (["exam", "exercise_collection"].includes(d.kind)) {
                          setSource(
                            await api(
                              "/api/library/nodes/" +
                                encodeURIComponent(toc.items[0].id) +
                                "/bundle",
                            ),
                          );
                          return;
                        }
                        setSource({
                          document: d,
                          children: toc.items,
                          content: "",
                          assets: [],
                        });
                      })
                    }
                  >
                    {d.kind === "exam"
                      ? "افتح الامتحان وحلّه"
                      : d.kind === "exercise_collection"
                        ? "افتح سلسلة التمارين كاملة"
                        : "استكشف الفهرس"}
                  </button>
                </div>
              ))
            )}
          </section>
        )}
        {view === "models" && (
          <section className="page-content narrow">
            <h1>نموذج واحد لكل تشغيل</h1>
            <p className="muted">
              إعدادات التدريس مستقلة عن استخراج الكتب. التغيير يخص التشغيلات
              الجديدة؛ المفاتيح لا تُعرض بعد حفظها.
            </p>
            <form
              className="panel"
              onSubmit={(e) => {
                e.preventDefault();
                action(async () => {
                  const config: any = { ...model };
                  delete config.id;
                  delete config.slot;
                  delete config.key_saved;
                  await api("/api/owner/models/" + slot, "PUT", {
                    config,
                    api_key: key,
                  });
                  setKey("");
                  await navigate("models");
                  setNotice(
                    "حُفظ الإعداد مشفرًا. لم يُرسل طلب تدريس أو Vision.",
                  );
                });
              }}
            >
              <label>
                الاستخدام
                <select
                  value={slot}
                  onChange={(e) => {
                    setSlot(e.target.value);
                    const m = models.find((m) => m.slot === e.target.value);
                    if (m) setModel(m);
                    setKey("");
                  }}
                >
                  <option value="agent">وكيل التدريس</option>
                  <option value="extraction">استخراج الكتب</option>
                </select>
              </label>
              <label>
                Base URL
                <input
                  type="url"
                  dir="ltr"
                  required
                  value={model.base_url}
                  onChange={(e) =>
                    setModel({ ...model, base_url: e.target.value })
                  }
                />
              </label>
              <label>
                Model
                <input
                  dir="ltr"
                  required
                  value={model.model}
                  onChange={(e) =>
                    setModel({ ...model, model: e.target.value })
                  }
                />
              </label>
              <label>
                API Key
                <input
                  type="password"
                  autoComplete="off"
                  dir="ltr"
                  value={key}
                  placeholder={
                    models.some((m) => m.slot === slot)
                      ? "مفتاح محفوظ — اترك الحقل فارغًا للاحتفاظ به"
                      : "أدخل المفتاح؛ لا يُضمّن في المتصفح أو Git"
                  }
                  onChange={(e) => setKey(e.target.value)}
                />
              </label>
              <div className="form-columns">
                <label>
                  Temperature
                  <input
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    value={model.temperature}
                    onChange={(e) =>
                      setModel({
                        ...model,
                        temperature: Number(e.target.value),
                      })
                    }
                  />
                </label>
                <label>
                  حد رموز الإخراج
                  <input
                    type="number"
                    min="500"
                    max="32000"
                    value={model.max_tokens}
                    onChange={(e) =>
                      setModel({ ...model, max_tokens: Number(e.target.value) })
                    }
                  />
                </label>
              </div>
              <fieldset>
                <legend>
                  أسعار تقديرية لكل مليون رمز — وحدة العملة التي تعتمدها
                </legend>
                <p>
                  اتركها فارغة إن لم تعرف السعر. لن نفترض تكلفة صفرًا أو خصم
                  Cache غير مبلّغ.
                </p>
                {(
                  [
                    "input_price_per_million",
                    "output_price_per_million",
                    "cached_price_per_million",
                  ] as const
                ).map((k, i) => (
                  <label key={k}>
                    {
                      [
                        "سعر الإدخال",
                        "سعر الإخراج",
                        "سعر الإدخال المخزّن Cache",
                      ][i]
                    }
                    <input
                      type="number"
                      min="0"
                      step="any"
                      value={model[k] ?? ""}
                      onChange={(e) =>
                        setModel({
                          ...model,
                          [k]:
                            e.target.value === ""
                              ? null
                              : Number(e.target.value),
                        })
                      }
                    />
                  </label>
                ))}
              </fieldset>
              <button
                type="button"
                disabled={busy}
                onClick={() => {
                  if (
                    confirm(
                      "طلب اتصال صريح إلى GET /models فقط، بلا توليد نص أو صورة. هل تتابع؟",
                    )
                  )
                    action(async () => {
                      const r = await api(
                        `/api/owner/models/${slot}/test`,
                        "POST",
                        { confirm: true },
                      );
                      setNotice(
                        r.connected
                          ? "الاتصال نجح؛ هذا لا يثبت دعم الرؤية أو جودة أدوات النموذج. ظهور النموذج: " +
                              r.model_advertised
                          : "تعذر الاتصال",
                      );
                    });
                }}
              >
                اختبار الاتصال المحفوظ
              </button>
              {slot === "extraction" && (
                <label>
                  Structured output
                  <select
                    value={model.output_mode}
                    onChange={(e) =>
                      setModel({ ...model, output_mode: e.target.value })
                    }
                  >
                    <option value="json_object">JSON object</option>
                    <option value="json_schema">JSON schema</option>
                    <option value="none">Prompt only</option>
                  </select>
                </label>
              )}
              <button className="primary" disabled={busy}>
                حفظ الإعداد
              </button>
            </form>
          </section>
        )}
        {[
          "preferences",
          "notes",
          "materials",
          "accounts",
          "personal-usage",
        ].includes(view) &&
          (() => {
            const props = {
              api,
              role: user.role,
              chat: chatId,
              notify: setNotice,
              request: requestMaterial,
              render: (blocks: any[]) => <Content blocks={blocks} />,
            };
            return view === "preferences" ? (
              <PreferencesPanel {...props} />
            ) : view === "notes" ? (
              <NotesPanel {...props} />
            ) : view === "materials" ? (
              <MaterialsPanel {...props} />
            ) : view === "accounts" ? (
              <AccountsPanel {...props} />
            ) : (
              <PersonalUsage {...props} />
            );
          })()}
        {view === "security" && <SecurityPanel api={api} notify={setNotice} />}
        {view === "service-tokens" && user.role === "owner" && (
          <ServiceTokens api={api} notify={setNotice} />
        )}
        {view === "owner-library" && (
          <section className="page-content">
            <h1>من المصدر إلى نسخة معتمدة</h1>
            <p className="muted">
              رفع ← معاينة ← معالجة ← مراجعة ← نشر. لا تُستبدل النسخة المنشورة
              بمسودة جديدة بصمت.
            </p>
            <div className="owner-layout">
              <form className="panel" onSubmit={upload}>
                <h2>إضافة مصدر</h2>
                <label className="file-drop">
                  اختر ملف PDF
                  <input
                    type="file"
                    required
                    accept=".pdf,application/pdf"
                    onChange={(e) => {
                      setUploadFile(e.target.files?.[0] || null);
                      if (e.target.files?.[0])
                        setMeta({
                          ...meta,
                          title: e.target.files[0].name.replace(/\.pdf$/i, ""),
                          kind: /فرض|اختبار|بكالوريا|exam|bac\b/i.test(
                            e.target.files[0].name,
                          )
                            ? "exam"
                            : /تمارين|exercices|exercises/i.test(
                                  e.target.files[0].name,
                                )
                              ? "exercise_collection"
                              : /ملخص|قوانين|summary|formula/i.test(
                                    e.target.files[0].name,
                                  )
                                ? "reference"
                                : "book",
                        });
                    }}
                  />
                </label>
                <label>
                  العنوان
                  <input
                    required
                    value={meta.title}
                    onChange={(e) =>
                      setMeta({ ...meta, title: e.target.value })
                    }
                  />
                </label>
                <label>
                  نوع المستند
                  <select
                    value={meta.kind}
                    onChange={(e) => setMeta({ ...meta, kind: e.target.value })}
                  >
                    <option value="book">كتاب مدرسي أو خارجي</option>
                    <option value="exam">امتحان — الحل اختياري ومطابق</option>
                    <option value="exercise_collection">
                      سلسلة تمارين كاملة
                    </option>
                    <option value="reference">مرجع أو ملخص</option>
                  </select>
                </label>
                <div className="form-columns">
                  <label>
                    المادة
                    <input
                      required
                      value={meta.subject}
                      onChange={(e) =>
                        setMeta({ ...meta, subject: e.target.value })
                      }
                    />
                  </label>
                  <label>
                    التخصص
                    <input
                      required
                      value={meta.track}
                      onChange={(e) =>
                        setMeta({ ...meta, track: e.target.value })
                      }
                    />
                  </label>
                </div>
                {["exam", "exercise_collection"].includes(meta.kind) && (
                  <div className="form-columns">
                    {[
                      ["year", "السنة"],
                      ["session", "الدورة"],
                      ["exam_type", "نوع الامتحان"],
                      ["institution", "المؤسسة"],
                    ].map(([k, label]) => (
                      <label key={k}>
                        {label}
                        <input
                          value={(meta as any)[k]}
                          onChange={(e) =>
                            setMeta({ ...meta, [k]: e.target.value })
                          }
                        />
                      </label>
                    ))}
                  </div>
                )}
                <p className="muted">
                  نوع المستند اقتراح قابل للتغيير؛ راجعه قبل المعالجة.
                </p>
                <label>
                  المصدر / المرجع
                  <input
                    value={meta.source}
                    onChange={(e) =>
                      setMeta({ ...meta, source: e.target.value })
                    }
                  />
                </label>
                <button className="primary" disabled={busy || !uploadFile}>
                  رفع للمراجعة — ليس للنشر
                </button>
              </form>
              <div>
                <h2>المستندات</h2>
                {!ownerDocs.length && (
                  <p className="muted">لم تُرفع مستندات بعد.</p>
                )}
                {ownerDocs.map((d) => (
                  <div className="document-row" key={d.id}>
                    <div>
                      <h3>{d.title}</h3>
                      <p className="muted">
                        {d.status} ·{" "}
                        {d.published_version ? "نسخة منشورة" : "مسودة فقط"}
                      </p>
                      {d.versions.map((v: any) => (
                        <button
                          key={v.id}
                          className="version-button"
                          onClick={() =>
                            action(async () => {
                              setVersion(
                                await api("/api/owner/versions/" + v.id),
                              );
                              setReviewPage(null);
                            })
                          }
                        >
                          نسخة {v.sequence} · {v.status}
                        </button>
                      ))}
                    </div>
                    <button
                      onClick={() =>
                        action(async () => {
                          await api(
                            "/api/owner/documents/" + d.id + "/status",
                            "PATCH",
                            {
                              status:
                                d.status === "ARCHIVED" ? "ACTIVE" : "ARCHIVED",
                            },
                          );
                          await navigate("owner-library");
                        })
                      }
                    >
                      {d.status === "ARCHIVED" ? "استعادة" : "أرشفة"}
                    </button>
                  </div>
                ))}
              </div>
            </div>
            {version && (
              <div className="panel version-panel">
                <div className="section-heading">
                  <h2>مراجعة النسخة {version.sequence}</h2>
                  <span className="status">
                    {version.extraction_status} · {version.status}
                  </span>
                </div>
                <BundleEditor
                  version={version}
                  api={api}
                  action={action}
                  refresh={refreshVersion}
                  onClone={setVersion}
                />
                <div className="actions">
                  <button
                    disabled={
                      busy ||
                      ["REVIEWED", "PUBLISHED"].includes(version.status) ||
                      version.files?.some(
                        (f: any) => f.extraction_status === "PROCESSING",
                      )
                    }
                    onClick={() =>
                      action(async () => {
                        await api(
                          "/api/owner/versions/" + version.id + "/process",
                          "POST",
                          {},
                        );
                        setVersion(
                          await api("/api/owner/versions/" + version.id),
                        );
                      })
                    }
                  >
                    بدء المعالجة
                  </button>
                  <button
                    onClick={() =>
                      action(async () => {
                        const r = await api(
                          "/api/owner/versions/" + version.id + "/retry/failed",
                          "POST",
                          {},
                        );
                        setNotice(
                          "أُعيدت جدولة " + r.scheduled + " صفحة فاشلة فقط.",
                        );
                      })
                    }
                  >
                    إعادة الفاشلة
                  </button>
                  <button
                    onClick={() =>
                      action(async () => {
                        const r = await api(
                          "/api/owner/versions/" +
                            version.id +
                            "/retry/suspicious",
                          "POST",
                          {},
                        );
                        setNotice(
                          "أُعيدت جدولة " +
                            r.scheduled +
                            " صفحة مشكوك فيها فقط.",
                        );
                      })
                    }
                  >
                    إعادة المشكوك فيها
                  </button>
                </div>
                {version.files?.map((f: any) => (
                  <div key={f.id}>
                    <h3>
                      {f.role === "primary" ? "صفحات المصدر" : "صفحات الحل"} ·{" "}
                      {f.filename}
                    </h3>
                    <div className="page-list">
                      {f.pages?.map((p: any) => (
                        <button
                          key={p.pdf_page}
                          className={p.quality.length ? "needs-review" : ""}
                          onClick={() =>
                            action(async () =>
                              setReviewPage({
                                ...(await api(
                                  "/api/owner/versions/" +
                                    version.id +
                                    "/page/" +
                                    p.pdf_page +
                                    "?file_id=" +
                                    encodeURIComponent(f.id),
                                )),
                                file_id: f.id,
                                role: f.role,
                              }),
                            )
                          }
                        >
                          {f.role === "solution" ? "الحل · " : ""}ص {p.pdf_page}{" "}
                          · {p.status}
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
                {reviewPage && (
                  <div className="review-grid">
                    <div>
                      <h3>المصدر الأصلي · ص {reviewPage.page}</h3>
                      <img
                        className="source-page"
                        src={
                          "/api/owner/versions/" +
                          version.id +
                          "/page/" +
                          reviewPage.page +
                          "/image?file_id=" +
                          encodeURIComponent(reviewPage.file_id)
                        }
                        alt="صفحة المصدر الأصلية"
                      />
                    </div>
                    <div>
                      <h3>النص المستخرج</h3>
                      {reviewPage.quality.length > 0 && (
                        <p className="warning">
                          {reviewPage.quality.join(" · ")}
                        </p>
                      )}
                      <pre>
                        {reviewPage.content ||
                          "لم تُعالج الصفحة بعد؛ يمكنك معاينة الصورة دون طلب Vision."}
                      </pre>
                    </div>
                  </div>
                )}
                <label className="check">
                  <input
                    type="checkbox"
                    checked={ack}
                    onChange={(e) => setAck(e.target.checked)}
                  />
                  راجعت المصدر وأقرّ بتحذيرات الجودة الظاهرة إن وجدت.
                </label>
                <label>
                  ملاحظات المراجعة
                  <textarea
                    value={reviewNotes}
                    onChange={(e) => setReviewNotes(e.target.value)}
                  />
                </label>
                <div className="actions">
                  <button
                    disabled={
                      busy ||
                      !ack ||
                      ["REVIEWED", "PUBLISHED"].includes(version.status) ||
                      version.files?.some(
                        (f: any) =>
                          !f.extraction_status.startsWith("COMPLETED") ||
                          (f.role === "solution" &&
                            f.verification !== "owner_verified"),
                      )
                    }
                    onClick={() =>
                      action(async () => {
                        await api(
                          "/api/owner/versions/" + version.id + "/review",
                          "POST",
                          { acknowledge_issues: ack, notes: reviewNotes },
                        );
                        setVersion(
                          await api("/api/owner/versions/" + version.id),
                        );
                      })
                    }
                  >
                    اعتماد المراجعة
                  </button>
                  <button
                    className="primary"
                    disabled={busy || version.status !== "REVIEWED"}
                    onClick={() =>
                      action(async () => {
                        await api(
                          "/api/owner/versions/" + version.id + "/publish",
                          "POST",
                          {},
                        );
                        setVersion(
                          await api("/api/owner/versions/" + version.id),
                        );
                        setNotice(
                          "نُشرت النسخة المعتمدة وأصبحت متاحة للأدوات والطلاب.",
                        );
                        setOwnerDocs((await api("/api/owner/documents")).items);
                      })
                    }
                  >
                    نشر للطلاب
                  </button>
                </div>
              </div>
            )}
          </section>
        )}
        {view === "usage" && (
          <section className="page-content">
            <h1>استخدام معلَن، لا تقديرات وهمية</h1>
            <p className="muted">
              تُحفظ الأرقام التي يعيدها المزوّد فقط. التكلفة لا تتوفر دون أسعار
              مهيّأة؛ Cache غير المبلّغ عنه يظهر كغير متاح.
            </p>
            {usage && (
              <>
                <p>طلبات بلا بيانات استخدام: {usage.missing_usage_calls}</p>
                <p>
                  المحاسبة آخر {usage.days} يومًا. بيانات Cache والأسعار
                  المفقودة ليست صفرًا؛ مجموعات جزئية تُعرض أدناه.
                </p>
                <pre className="material-solution" dir="ltr">
                  {JSON.stringify(
                    {
                      file_cache: usage.file_cache,
                      runs: usage.runs,
                      reporting: usage.items.map((u: any) => ({
                        model: u.model,
                        feature: u.feature,
                        errors: u.errors,
                        missing_usage: u.missing_usage,
                        missing_cache: u.missing_cache,
                        missing_cost: u.missing_cost,
                      })),
                    },
                    null,
                    2,
                  )}
                </pre>
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        {[
                          "النموذج",
                          "الميزة",
                          "الطلبات",
                          "رموز الإدخال",
                          "رموز الإخراج",
                          "Cache",
                          "تكلفة تقديرية",
                          "الكمون ms",
                        ].map((x) => (
                          <th key={x}>{x}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {usage.items.map((u: any) => (
                        <tr key={u.model + ":" + u.feature}>
                          {[
                            "model",
                            "feature",
                            "calls",
                            "input_tokens",
                            "output_tokens",
                            "cached_tokens",
                            "estimated_cost",
                            "latency_ms",
                          ].map((k) => (
                            <td key={k}>{u[k] ?? "غير متاح"}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </section>
        )}
      </div>
      {source && (
        <div className="modal-backdrop" onClick={() => setSource(null)}>
          <section
            className="source-modal"
            role="dialog"
            aria-modal="true"
            aria-label="المصدر التعليمي"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="section-heading">
              <h2>{source.node?.title || source.document?.title}</h2>
              <button onClick={() => setSource(null)} aria-label="إغلاق المصدر">
                ×
              </button>
            </div>
            {source.atomic_bundle && (
              <p className="info">
                حزمة كاملة: الموضوع والحل المرفق إن وجد. لا تُجزّأ إلى أسئلة
                مستقلة.
              </p>
            )}
            {source.part && (
              <p className="info">
                جزء {source.part.part_index + 1} من الدرس · الاستشهاد يخص هذا
                الجزء فقط.
              </p>
            )}
            {source.parts?.length > 1 && (
              <details>
                <summary>
                  أجزاء الدرس الطويل — دون قطع الجداول والمعادلات
                </summary>
                {source.parts.map((p: any) => (
                  <button
                    className="node-row"
                    key={p.id}
                    onClick={() => readPart(p.id)}
                  >
                    جزء {p.part_index + 1} · {p.metadata.title} · ص{" "}
                    {p.metadata.pages.join("، ")}
                  </button>
                ))}
              </details>
            )}
            {source.private_image && (
              <img src={source.private_image} alt="المصدر الخاص المؤقت" />
            )}
            {source.content && <Md text={source.content} />}
            {source.atomic_bundle &&
              (source.solution ? (
                <details className="solution-view">
                  <summary>عرض الحل المرفق — مطابق بتأكيد المالك</summary>
                  <p className="muted">
                    مصدر الحل: {source.solution.provenance.source}.{" "}
                    {source.solution.provenance.designation ===
                    "official_source"
                      ? "النسبة لمصدر رسمي وصفٌ قدّمه المالك، وليست شهادة من النموذج."
                      : "حل مرفق، غير مصنّف رسميًا."}
                  </p>
                  <Md text={source.solution.content} />
                </details>
              ) : (
                <p className="warning">
                  الحل غير متاح لهذا المصدر. لا يتم اختراع حل رسمي.
                </p>
              ))}
            <div>
              {source.children?.map((n: any) => (
                <button
                  className="node-row"
                  key={n.id}
                  onClick={() => readSource(n.id)}
                >
                  {n.kind} · {n.title} · ص{" "}
                  <bdi dir="ltr">
                    {n.start_page}–{n.end_page}
                  </bdi>
                </button>
              ))}
            </div>
            {source.sources?.map((src: Source, i: number) => (
              <a
                key={i}
                className="source-link"
                href={
                  "/api/library/documents/" +
                  src.document_id +
                  "/page/" +
                  src.pages[0] +
                  (src.file_id
                    ? "?file_id=" + encodeURIComponent(src.file_id)
                    : "")
                }
                target="_blank"
                rel="noopener"
              >
                عرض صفحة {src.role === "solution" ? "الحل" : "المصدر"}{" "}
                {src.pages[0]}
              </a>
            ))}
          </section>
        </div>
      )}
    </div>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
