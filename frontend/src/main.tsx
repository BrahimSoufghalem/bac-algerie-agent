import React, { useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import Markdown from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import { normalizeMathDelimiters } from "./markdownMath";
import "katex/dist/katex.min.css";
import "@fontsource/noto-sans-arabic/400.css";
import "@fontsource/noto-sans-arabic/600.css";
import "@fontsource/noto-sans-arabic/700.css";
import "./style.css";
import {
  Icon,
  Mark,
  Dialog,
  CopyAnswer,
  useAppearance,
  useSidebar,
  type IconName,
} from "./ChatUI";
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
        img: () => null,
        td: ({ children }) => <td dir="auto">{children}</td>,
        th: ({ children }) => <th dir="auto">{children}</th>,
        table: ({ children }) => (
          <div className="table-scroll">
            <table>{children}</table>
          </div>
        ),
      }}
    >
      {normalizeMathDelimiters(text)}
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
          </div>
        ) : b.type === "image" ? null : b.type === "table" ? (
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
        ) : b.type === "verification" && b.result ? null : b.type === "graph" &&
          b.result ? (
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
  const { appearance, setAppearance } = useAppearance();
  const { collapsed, setCollapsed } = useSidebar();
  const [accountOpen, setAccountOpen] = useState(false);
  const [chatDialog, setChatDialog] = useState<{
    kind: "rename" | "delete";
    chat: Chat;
  } | null>(null);
  const [renameTitle, setRenameTitle] = useState("");
  const [showLatest, setShowLatest] = useState(false);
  const scrollArea = useRef<HTMLDivElement>(null);
  const composerInput = useRef<HTMLTextAreaElement>(null);
  const pinned = useRef(true);
  const accountRef = useRef<HTMLDivElement>(null);
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
    setText("");
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
    setAccountOpen(false);
    pinned.current = true;
    setShowLatest(false);
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
    for (const kind of ["queued", "answer", "error"])
      es.addEventListener(kind, (event: Event) => {
        const e = event as MessageEvent;
        if (!e.data) return;
        const eid = Number(e.lastEventId);
        if (seen.has(eid)) return;
        seen.add(eid);
        const p = JSON.parse(e.data);
        if (kind === "answer") {
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
          setNotice(p.label);
          setRun("");
          es.close();
        }
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
  function jumpToLatest() {
    pinned.current = true;
    setShowLatest(false);
    const area = scrollArea.current;
    if (area) area.scrollTop = area.scrollHeight;
  }
  useEffect(() => {
    if (pinned.current) jumpToLatest();
  }, [delta, messages.length, view, chatId]);
  useEffect(() => {
    const area = scrollArea.current;
    const content = area?.querySelector(".conversation");
    if (!content) return;
    const observer = new ResizeObserver(() => {
      if (pinned.current) jumpToLatest();
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, [view, chatId, messages.length]);
  useEffect(() => {
    const input = composerInput.current;
    if (input) {
      input.style.height = "auto";
      input.style.height =
        Math.min(180, Math.max(54, input.scrollHeight)) + "px";
    }
  }, [text, view]);
  useEffect(() => {
    if (!accountOpen) return;
    const outside = (e: PointerEvent) => {
      if (!accountRef.current?.contains(e.target as Node))
        setAccountOpen(false);
    };
    const keydown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setAccountOpen(false);
        accountRef.current
          ?.querySelector<HTMLButtonElement>(".profile-button")
          ?.focus();
      }
    };
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", keydown);
    };
  }, [accountOpen]);
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
      if (d.verification_required) {
        setAuthMode("login");
        setError("راجع بريدك لتأكيد الحساب قبل الدخول.");
        return;
      }
      csrf = d.csrf;
      setUser(d.user);
      await refreshChats();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function createChat() {
    // Clear synchronously, not after network I/O: typing during creation must survive.
    stream.current?.close();
    setRun("");
    setDelta("");
    setActivities([]);
    setWarnings([]);
    setChatId("");
    setMessages([]);
    setText("");
    setEditing("");
    setView("chat");
    setMenu(false);
    setAccountOpen(false);
    setSource(null);
    pinned.current = true;
    setShowLatest(false);
    const c = await api("/api/conversations", "POST", {});
    setChatId(c.id);
    location.hash = "chat=" + c.id;
    await refreshChats();
    return c.id as string;
  }
  // Uploading from the empty composer creates a conversation without clearing its draft.
  const ensureAttachmentChat = () =>
    action(async () => {
      if (chatId) return chatId;
      const c = await api("/api/conversations", "POST", {});
      setChatId(c.id);
      location.hash = "chat=" + c.id;
      await refreshChats();
      return c.id as string;
    });
  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    if (!text.trim() || run || busy) return;
    pinned.current = true;
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
    setAccountOpen(false);
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
      return await fn();
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
      setNotice(
        "حُفظت نسخة خام. عاين المصدر قبل بدء Vision؛ لم تُتفعيل للوكيل.",
      );
    });
  }
  const isEmpty = messages.length === 0 && !run;
  const titles: Record<string, string> = {
    chat: "مسار",
    library: "المكتبة المنشورة",
    "owner-library": "مراجعة المحتوى ونشره",
    models: "نماذج التدريس والاستخراج",
    usage: "الاستخدام والمحاسبة",
    security: "أمان الحساب",
    "service-tokens": "وصول الوكلاء",
    preferences: "تفضيلات وخصوصية",
    notes: "ملاحظاتي التعليمية",
    materials: "المسودات التعليمية",
    accounts: "الحسابات والحدود",
    "personal-usage": "استخدامي وحدودي",
  };
  const navItem = (
    next: string,
    label: string,
    icon: IconName,
    accessible = label,
  ) => (
    <button
      key={next}
      title={label}
      aria-label={accessible}
      aria-current={view === next ? "page" : undefined}
      className={view === next ? "active" : ""}
      onClick={() => navigate(next)}
    >
      <Icon name={icon} />
      <span>{label}</span>
    </button>
  );
  const retryAnswer = () =>
    action(async () => {
      const d = await api(
        "/api/conversations/" + chatId + "/retry",
        "POST",
        {},
      );
      setMessages((await api("/api/conversations/" + chatId)).messages);
      pinned.current = true;
      subscribe(d.run_id);
    });
  const starters =
    user?.role === "teacher"
      ? [
          {
            icon: "book" as IconName,
            label: "حضّر درسًا",
            prompt: "حضّر خطة درس اعتمادًا على المكتبة",
          },
          {
            icon: "practice" as IconName,
            label: "أنشئ تدريبًا",
            prompt: "أنشئ اختبارًا تدريبيًا غير رسمي مع سلم تصحيح",
          },
          {
            icon: "note" as IconName,
            label: "راجع شرحي",
            prompt: "راجع شرحًا أعددته للطلاب",
          },
        ]
      : [
          {
            icon: "book" as IconName,
            label: "افهم درسًا",
            prompt: "اشرح لي درسًا خطوة بخطوة",
          },
          {
            icon: "write" as IconName,
            label: "راجع حلي",
            prompt: "ساعدني على فهم خطئي في الحل",
          },
          {
            icon: "practice" as IconName,
            label: "افهم قانونًا",
            prompt: "اشرح لي قانونًا في الفيزياء بطريقة مبسطة",
          },
        ];
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
          <div className="brand">
            <Mark />
            <strong>مسار</strong>
            <span>مساحة التعلّم</span>
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
            <Icon name="book" /> من المصدر إلى الفهم، خطوة بخطوة.
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
    <div className={"app " + (collapsed ? "sidebar-collapsed" : "")}>
      <a
        className="skip-link"
        href="#workspace-content"
        onClick={(e) => {
          e.preventDefault();
          if (view === "chat") composerInput.current?.focus();
          else document.getElementById("workspace-content")?.focus();
        }}
      >
        انتقل إلى المحتوى
      </a>
      {menu && (
        <div
          className="drawer-backdrop"
          aria-hidden="true"
          onClick={() => setMenu(false)}
        />
      )}
      <aside
        id="conversation-sidebar"
        aria-label="الشريط الجانبي"
        className={"sidebar " + (menu ? "open" : "")}
        inert={Boolean(source || chatDialog)}
      >
        <div className="sidebar-top">
          <button
            className="brand"
            aria-label="مسار · المحادثة"
            onClick={() => navigate("chat")}
          >
            <Mark small />
            <strong>مسار</strong>
          </button>
          <button
            className="icon-button sidebar-toggle"
            aria-label={
              collapsed ? "توسيع الشريط الجانبي" : "طي الشريط الجانبي"
            }
            title={collapsed ? "توسيع الشريط" : "طي الشريط"}
            onClick={() => {
              setCollapsed(!collapsed);
              setAccountOpen(false);
            }}
          >
            <Icon name="panel" />
          </button>
          <button
            className="icon-button drawer-close"
            aria-label="إغلاق القائمة"
            onClick={() => setMenu(false)}
          >
            <Icon name="close" />
          </button>
        </div>
        <nav aria-label="مساحة التعلّم" className="primary-nav">
          <button
            className="new-chat"
            aria-label="＋ محادثة جديدة"
            title="محادثة جديدة"
            onClick={() => action(createChat)}
            disabled={busy}
          >
            <Icon name="write" />
            <span>محادثة جديدة</span>
            <kbd>جديد</kbd>
          </button>
          {user.role !== "student" &&
            navItem("materials", "مساحة إعداد الأستاذ", "practice")}
        </nav>
        <label className="chat-search">
          <Icon name="search" size={17} />
          <input
            placeholder="ابحث في محادثاتك"
            aria-label="البحث في المحادثات"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="history-caption">محادثاتك</div>
        <div className="chat-history">
          {!chats.length && (
            <p className="history-empty">
              {query
                ? "لا توجد محادثات بهذا العنوان."
                : "سؤالك الأول يبدأ مسارًا جديدًا."}
            </p>
          )}
          {chats.map((c) => (
            <div
              key={c.id}
              className={"history-item " + (c.id === chatId ? "selected" : "")}
            >
              <button
                aria-current={
                  c.id === chatId && view === "chat" ? "page" : undefined
                }
                onClick={() => action(() => openChat(c.id))}
                title={c.title}
              >
                {c.title}
              </button>
              <details>
                <summary aria-label="خيارات المحادثة">
                  <Icon name="more" size={18} />
                </summary>
                <div className="history-actions">
                  <button
                    onClick={(e) => {
                      e.currentTarget
                        .closest("details")
                        ?.removeAttribute("open");
                      setRenameTitle(c.title);
                      setChatDialog({ kind: "rename", chat: c });
                    }}
                  >
                    <Icon name="write" size={16} /> إعادة تسمية
                  </button>
                  <button
                    className="destructive-text"
                    onClick={(e) => {
                      e.currentTarget
                        .closest("details")
                        ?.removeAttribute("open");
                      setChatDialog({ kind: "delete", chat: c });
                    }}
                  >
                    <Icon name="trash" size={16} /> حذف
                  </button>
                </div>
              </details>
            </div>
          ))}
        </div>
        <div className="profile" ref={accountRef}>
          <button
            className="profile-button"
            aria-label="إعدادات الحساب"
            aria-expanded={accountOpen}
            aria-controls="account-panel"
            onClick={() => {
              setCollapsed(false);
              setAccountOpen(!accountOpen);
            }}
          >
            <span className="avatar">{user.name.trim().slice(0, 1)}</span>
            <span className="profile-text">
              <strong>{user.name}</strong>
              <small>
                {user.role === "owner"
                  ? "مساحة المالك"
                  : user.role === "teacher"
                    ? "مساحة الأستاذ"
                    : "مساحة الطالب"}
              </small>
            </span>
            <Icon name="chevron" size={16} />
          </button>
          {accountOpen && (
            <div
              id="account-panel"
              className="account-panel"
              aria-label="إعدادات ومساحات الحساب"
            >
              <div className="account-heading">إعدادات مساحتك</div>
              <nav aria-label="إعدادات الحساب والتنقل">
                {navItem("preferences", "تفضيلات وخصوصية", "settings")}
                {navItem("notes", "ملاحظات مسار التعليمية", "note")}
                {navItem("security", "أمان الحساب", "shield")}
                {navItem("personal-usage", "استخدامي وحدودي", "chart")}
                {user.role === "owner" && (
                  <>
                    <div className="account-heading">إدارة المالك</div>
                    {navItem(
                      "owner-library",
                      "إدارة المحتوى",
                      "book",
                      "▥ إدارة المحتوى",
                    )}
                    {navItem(
                      "models",
                      "إعداد النماذج",
                      "settings",
                      "⚙ إعداد النماذج",
                    )}
                    {navItem("usage", "الاستخدام", "chart", "◷ الاستخدام")}
                    {navItem("accounts", "الحسابات والحدود", "users")}
                  </>
                )}
              </nav>
              <div
                className="appearance-controls"
                role="group"
                aria-label="مظهر الواجهة"
              >
                {(
                  [
                    ["light", "فاتح", "sun"],
                    ["dark", "داكن", "moon"],
                    ["system", "تلقائي", "monitor"],
                  ] as const
                ).map(([value, label, icon]) => (
                  <button
                    key={value}
                    title={label}
                    aria-label={"مظهر " + label}
                    aria-pressed={appearance === value}
                    onClick={() => setAppearance(value)}
                  >
                    <Icon name={icon} size={17} />
                    <span>{label}</span>
                  </button>
                ))}
              </div>
              <button
                className="logout-button"
                onClick={() =>
                  action(async () => {
                    await api("/api/auth/logout", "POST", {});
                    stream.current?.close();
                    setUser(null);
                    setMessages([]);
                    setChats([]);
                    setChatId("");
                    setAccountOpen(false);
                    setText("");
                    setMenu(false);
                    csrf = "";
                  })
                }
              >
                <Icon name="logout" size={18} /> خروج
              </button>
            </div>
          )}
        </div>
      </aside>
      <div
        id="workspace-content"
        tabIndex={-1}
        className="workspace"
        inert={Boolean(menu || source || chatDialog)}
      >
        <header className="topbar">
          <div className="topbar-start">
            <button
              className="icon-button menu-button"
              onClick={() => setMenu(!menu)}
              aria-label="فتح القائمة"
              aria-controls="conversation-sidebar"
              aria-expanded={menu}
            >
              <Icon name="menu" />
            </button>
            <button
              className="workspace-brand"
              aria-label="مسار · العودة للمحادثة"
              onClick={() => navigate("chat")}
            >
              {view === "chat" ? "مسار" : titles[view]}
              {view === "chat" && (
                <span className="assistant-badge">مساعد التعلّم</span>
              )}
            </button>
          </div>
          <div className="topbar-actions">
            <span
              className="chat-title"
              title={chats.find((c) => c.id === chatId)?.title}
            >
              {view === "chat"
                ? chats.find((c) => c.id === chatId)?.title || "محادثة جديدة"
                : "مساحة خاصة"}
            </span>
            <button
              className="icon-button"
              title="محادثة جديدة"
              aria-label="بدء محادثة جديدة"
              onClick={() => action(createChat)}
              disabled={busy}
            >
              <Icon name="write" />
            </button>
          </div>
        </header>
        {notice && (
          <div className="notice" role="status">
            <span>{notice}</span>
            <button
              className="icon-button"
              onClick={() => setNotice("")}
              aria-label="إغلاق التنبيه"
            >
              <Icon name="close" size={18} />
            </button>
          </div>
        )}
        {view === "chat" && (
          <div className={"chat-stage " + (isEmpty ? "empty" : "")}>
            <div
              className="chat-scroll"
              ref={scrollArea}
              onScroll={() => {
                const a = scrollArea.current;
                if (a) {
                  const near =
                    a.scrollHeight - a.scrollTop - a.clientHeight < 96;
                  pinned.current = near;
                  setShowLatest(!near);
                }
              }}
            >
              <section className="conversation" aria-label="المحادثة">
                {isEmpty ? (
                  <div className="welcome">
                    <Mark />
                    <p className="welcome-greeting">
                      أهلًا {user.name.split(" ")[0]}
                    </p>
                    <h1>
                      {user.role === "teacher"
                        ? "ما الذي نحضّره اليوم؟"
                        : "ما الذي تريد أن تفهمه اليوم؟"}
                    </h1>
                    <p className="welcome-caption">
                      فكرة، درس، أو مسألة. لنأخذها خطوة بخطوة.
                    </p>
                  </div>
                ) : (
                  messages.map((m, index) => (
                    <article className={"message " + m.role} key={m.id}>
                      {m.role === "assistant" && (
                        <div className="message-label">
                          <Mark small /> مسار
                        </div>
                      )}
                      <div className="message-body" dir="auto">
                        {m.blocks.length ? (
                          <Content blocks={m.blocks} />
                        ) : m.role === "user" ? (
                          <p className="user-text">{m.content}</p>
                        ) : (
                          <Md text={m.content} />
                        )}
                      </div>
                      <div className="message-actions">
                        {m.role === "user" ? (
                          !run && (
                            <button
                              className="icon-button"
                              aria-label="تعديل"
                              title="تعديل الرسالة"
                              onClick={() => {
                                setEditing(m.id);
                                setText(m.content);
                                composerInput.current?.focus();
                              }}
                            >
                              <Icon name="write" size={17} />
                            </button>
                          )
                        ) : (
                          <>
                            <CopyAnswer
                              text={
                                m.content ||
                                m.blocks
                                  .map(
                                    (b) =>
                                      b.text ||
                                      b.latex ||
                                      (b.headers
                                        ? [b.headers, ...(b.rows || [])]
                                            .map((row) => row.join(" | "))
                                            .join("\n")
                                        : b.caption || ""),
                                  )
                                  .join("\n\n")
                              }
                              notify={setNotice}
                            />
                            {!run && index === messages.length - 1 && (
                              <button
                                className="icon-button"
                                aria-label="إعادة محاولة الرسالة الأخيرة"
                                title="إعادة محاولة الرسالة الأخيرة"
                                onClick={retryAnswer}
                                disabled={busy}
                              >
                                <Icon name="retry" size={17} />
                              </button>
                            )}
                          </>
                        )}
                      </div>
                    </article>
                  ))
                )}
                {delta && (
                  <article className="message assistant streaming">
                    <div className="message-label">
                      <Mark small /> مسار{" "}
                      <span className="stream-label">بث مباشر</span>
                    </div>
                    <div className="message-body">
                      <Md text={delta} />
                    </div>
                  </article>
                )}
                {run && !delta && (
                  <div className="run-status" role="status">
                    <span className="pulse-dot" /> جارٍ تنفيذ طلبك…
                  </div>
                )}
                {warnings.map((w, i) => (
                  <p className="warning" key={i}>
                    {w}
                  </p>
                ))}
                <div ref={bottom} />
              </section>
            </div>
            <div className="composer-wrap">
              {showLatest && !isEmpty && (
                <button
                  className="jump-latest"
                  aria-label="العودة إلى أحدث رسالة"
                  onClick={jumpToLatest}
                >
                  <Icon name="down" size={18} />
                </button>
              )}
              {editing && (
                <div className="editing">
                  <span>تعديل الرسالة · سيُنشأ مسار جديد للردود التالية.</span>
                  <button
                    className="icon-button"
                    aria-label="إلغاء التعديل"
                    onClick={() => {
                      setEditing("");
                      setText("");
                    }}
                  >
                    <Icon name="close" size={17} />
                  </button>
                </div>
              )}
              <form className="composer" onSubmit={send}>
                <textarea
                  id="chat-input"
                  ref={composerInput}
                  aria-label="رسالتك"
                  placeholder={isEmpty ? "اسأل مسار…" : "تابع المحادثة…"}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  maxLength={8000}
                  rows={1}
                  onKeyDown={(e) => {
                    if (
                      e.key === "Enter" &&
                      !e.shiftKey &&
                      !e.nativeEvent.isComposing &&
                      e.keyCode !== 229
                    ) {
                      e.preventDefault();
                      send();
                    }
                  }}
                />
                <div className="composer-controls">
                  <div className="composer-tools">
                    <PrivateUploads
                      api={api}
                      chat={chatId}
                      ensureChat={ensureAttachmentChat}
                      notify={setNotice}
                    />
                    <span className="context-label">
                      <Icon name="shield" size={14} /> مساحة خاصة
                    </span>
                  </div>
                  <div className="send-controls">
                    <span className="key-hint">Shift + Enter لسطر جديد</span>
                    {run ? (
                      <button
                        className="send-button"
                        type="button"
                        aria-label="■ إيقاف"
                        title="إيقاف"
                        onClick={() =>
                          action(() =>
                            api("/api/runs/" + run + "/cancel", "POST", {}),
                          )
                        }
                      >
                        <Icon name="stop" size={18} />
                      </button>
                    ) : (
                      <button
                        className="send-button"
                        aria-label="إرسال ↑"
                        title="إرسال"
                        disabled={busy || !text.trim()}
                      >
                        <Icon name="arrow" size={21} />
                      </button>
                    )}
                  </div>
                </div>
              </form>
              <p className="composer-note">
                قد يخطئ مسار. تحقّق من المصادر والنتائج المهمة.
              </p>
            </div>
            {isEmpty && (
              <div className="starter-bar">
                {starters.map((s) => (
                  <button
                    key={s.label}
                    onClick={() => {
                      setText(s.prompt);
                      composerInput.current?.focus();
                    }}
                  >
                    <Icon name={s.icon} size={17} />
                    {s.label}
                  </button>
                ))}
              </div>
            )}
          </div>
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
        {view === "owner-library" && user.role === "owner" && (
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
                    تفعيل للوكيل
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
      {chatDialog && (
        <Dialog
          title={
            chatDialog.kind === "rename"
              ? "إعادة تسمية المحادثة"
              : "حذف المحادثة"
          }
          close={() => setChatDialog(null)}
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action(async () => {
                const c = chatDialog.chat;
                if (chatDialog.kind === "rename")
                  await api("/api/conversations/" + c.id, "PATCH", {
                    title: renameTitle.trim(),
                  });
                else {
                  await api("/api/conversations/" + c.id, "DELETE");
                  if (chatId === c.id) {
                    setChatId("");
                    setMessages([]);
                    setText("");
                    location.hash = "";
                  }
                }
                await refreshChats();
                setChatDialog(null);
              });
            }}
          >
            {chatDialog.kind === "rename" ? (
              <label>
                عنوان المحادثة
                <input
                  value={renameTitle}
                  maxLength={150}
                  required
                  onChange={(e) => setRenameTitle(e.target.value)}
                />
              </label>
            ) : (
              <p>
                سيُحذف «{chatDialog.chat.title}» ورسائله. لا يمكنك التراجع عن
                هذا الإجراء.
              </p>
            )}
            <div className="actions">
              <button
                className={
                  chatDialog.kind === "delete" ? "danger-button" : "primary"
                }
                disabled={
                  busy || (chatDialog.kind === "rename" && !renameTitle.trim())
                }
              >
                {chatDialog.kind === "rename" ? "حفظ العنوان" : "حذف نهائيًا"}
              </button>
              <button type="button" onClick={() => setChatDialog(null)}>
                إلغاء
              </button>
            </div>
            {notice && (
              <p role="alert" className="error">
                {notice}
              </p>
            )}
          </form>
        </Dialog>
      )}
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
