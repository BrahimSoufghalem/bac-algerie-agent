import { UsageSummary } from "./UsageUI";
import { Button } from "./components/ui/button";
import { Input } from "./components/ui/input";
import { NativeSelect } from "./components/ui/native-select";
import { Textarea } from "./components/ui/textarea";
import { Card } from "./components/ui/card";
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
import "./design/tokens.css";
import "./style.css";
import "./conversationRefinements.css";
import "./design/masar.css";
import {
  DesignProvider,
  Welcome,
  SubjectPicker,
  Starters,
  WorkspaceHeading,
  CountBadge,
} from "./BrandUI";
import { TooltipProvider } from "./components/ui/tooltip";
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
import {
  emptyCatalogue,
  StudyCatalogue,
} from "./StudyChoices";
import OwnerLibrary from "./OwnerLibrary";
import { RunActivity, type WorkActivity } from "./RunActivity";
import {
  ScientificChart,
  ScientificDiagram,
  ScientificResult,
} from "./ScienceBlocks";
type User = {
  id: string;
  name: string;
  role: string;
  study_track: string | null;
};
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
  activity?: WorkActivity;
  unanswered_activity?: WorkActivity;
  previous_activities?: WorkActivity[];
};
type Chat = { id: string; title: string; study_subject: string | null };
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
          <div
            tabIndex={0}
            role="region"
            aria-label="جدول قابل للتمرير"
            className="table-scroll"
          >
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
          <div
            tabIndex={0}
            role="region"
            aria-label="جدول قابل للتمرير"
            className="table-scroll"
            key={i}
          >
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
          <pre tabIndex={0} dir="ltr" key={i}>
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
  const dialogReturnFocus = useRef<HTMLElement | null>(null);
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
  const [studyCatalog, setStudyCatalog] =
    useState<StudyCatalogue>(emptyCatalogue);
  const [onboardingTrack, setOnboardingTrack] = useState("");
  const [subject, setSubject] = useState("");
  const allowedSubjects =
    studyCatalog.tracks.find((x) => x.id === user?.study_track)?.subjects || [];
  const needsSubject = user?.role === "student" && !subject;
  useEffect(() => {
    if (user)
      api("/api/study/catalogue")
        .then(setStudyCatalog)
        .catch((e) => setNotice(e.message));
  }, [user?.id]);
  const [chats, setChats] = useState<Chat[]>([]),
    [chatId, setChatId] = useState(""),
    [messages, setMessages] = useState<Message[]>([]),
    [query, setQuery] = useState(""),
    [text, setText] = useState(""),
    [editing, setEditing] = useState(""),
    [run, setRun] = useState(""),
    [delta, setDelta] = useState(""),
    [activeActivity, setActiveActivity] = useState<WorkActivity | null>(null),
    [expandedRuns, setExpandedRuns] = useState<Record<string, boolean>>({}),
    [warnings, setWarnings] = useState<string[]>([]),
    [source, setSource] = useState<any>(null);
  const stream = useRef<EventSource | null>(null);
  const chatLoad = useRef(0);
  const bottom = useRef<HTMLDivElement>(null);
  const [docs, setDocs] = useState<any[]>([]);
  const [busy, setBusy] = useState(false);
  const [providerPresets, setProviderPresets] = useState<any[]>([]);
  const [catalog, setCatalog] = useState<any[]>([]);
  const [models, setModels] = useState<any[]>([]),
    [slot, setSlot] = useState("agent"),
    [model, setModel] = useState<any>({
      provider: "openai",
      protocol: "openai",
      base_url: "https://api.openai.com/v1",
      model: "gpt-4.1-mini",
      selector_enabled: false,
      main_max_rounds: 4,
      max_context_chars: null,
      temperature: 0.1,
      focused_mode: true,
      max_tokens: 6000,
      timeout: 90,
      output_mode: "json_object",
      input_price_per_million: null as number | null,
      output_price_per_million: null as number | null,
      cached_price_per_million: null as number | null,
    }),
    [key, setKey] = useState(""),
    [usage, setUsage] = useState<any>(null);
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
    const load = ++chatLoad.current;
    setText("");
    stream.current?.close();
    setRun("");
    setDelta("");
    setActiveActivity(null);
    setWarnings([]);
    const c = await api("/api/conversations/" + id);
    if (load !== chatLoad.current) return;
    setActiveActivity(null);
    setChatId(id);
    setSubject(c.study_subject || "");
    setSource(null);
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
    setActiveActivity(null);
    const es = new EventSource("/api/runs/" + id + "/events");
    stream.current = es;
    const seen = new Set<string>();
    for (const kind of ["queued", "progress", "answer", "error"])
      es.addEventListener(kind, (event: Event) => {
        const e = event as MessageEvent;
        if (!e.data) return;
        const eid = `${kind}:${e.lastEventId}`;
        if (seen.has(eid)) return;
        seen.add(eid);
        const p = JSON.parse(e.data);
        if (kind === "progress") {
          setActiveActivity(p);
        } else if (kind === "answer") {
          setMessages((x) => [
            ...x.filter((m) => m.id !== p.message_id),
            {
              id: p.message_id,
              role: "assistant",
              content: "",
              blocks: p.blocks,
              sources: p.sources,
              activity: p.activity,
            },
          ]);
          setActiveActivity(null);
          setMessages((x) =>
            x.map((m) => ({
              ...m,
              unanswered_activity:
                m.unanswered_activity?.run_id === id
                  ? undefined
                  : m.unanswered_activity,
            })),
          );
          setWarnings(p.warnings || []);
          setDelta("");
          setRun("");
          es.close();
          refreshChats().catch(() => {});
        } else if (kind === "error") {
          setActiveActivity(null);
          setMessages((old) =>
            old.map((m) =>
              m.unanswered_activity?.run_id === id
                ? { ...m, unanswered_activity: p.activity }
                : m,
            ),
          );
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
        if (d.user.role === "student" && !d.user.study_track) return;
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
    if (user && (user.role !== "student" || user.study_track)) {
      const t = setTimeout(() => refreshChats().catch(() => {}), 250);
      return () => clearTimeout(t);
    }
  }, [query, user?.id, user?.study_track]);
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
      if (d.user.role !== "student" || d.user.study_track) await refreshChats();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function createChat() {
    ++chatLoad.current;
    // Clear synchronously, not after network I/O: typing during creation must survive.
    stream.current?.close();
    setRun("");
    setDelta("");
    setActiveActivity(null);
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
    if (needsSubject) {
      location.hash = "";
      setNotice("اختر مادة المحادثة من الزر العلوي");
      return "";
    }
    const c = await api("/api/conversations", "POST", {
      subject: subject || null,
    });
    setChatId(c.id);
    location.hash = "chat=" + c.id;
    await refreshChats();
    return c.id as string;
  }
  // Uploading from the empty composer creates a conversation without clearing its draft.
  const ensureAttachmentChat = () =>
    action(async () => {
      if (needsSubject) throw new Error("اختر مادة المحادثة أولًا");
      if (chatId) return chatId;
      const c = await api("/api/conversations", "POST", {
        subject: subject || null,
      });
      setChatId(c.id);
      location.hash = "chat=" + c.id;
      await refreshChats();
      return c.id as string;
    });
  async function send(e?: React.FormEvent) {
    e?.preventDefault();
    if (needsSubject) {
      setNotice("اختر مادة المحادثة أولًا");
      return;
    }
    if (!text.trim() || run || busy) return;
    pinned.current = true;
    setBusy(true);
    try {
      let id = chatId;
      if (!id) {
        const c = await api("/api/conversations", "POST", {
          title: text.slice(0, 65),
          subject: subject || null,
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
  async function chooseSubject(value: string) {
    if (!value) return;
    if (!chatId) {
      setSubject(value);
      return;
    }
    await action(async () => {
      const c = await api(`/api/conversations/${chatId}/subject`, "PUT", {
        value,
      });
      await openChat(c.id);
      await refreshChats();
      if (c.created_new)
        setNotice(
          "فُتحت محادثة جديدة للمادة المختارة؛ المحادثة السابقة محفوظة.",
        );
    });
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
      if (next === "models") {
        const [saved, offered] = await Promise.all([
          api("/api/owner/models"),
          api("/api/owner/model-presets?slot=" + slot),
        ]);
        const items = saved.items;
        setModels(items);
        setProviderPresets(offered.items);
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
  function toggleWork(id: string) {
    pinned.current = false;
    setExpandedRuns((old) => ({ ...old, [id]: !old[id] }));
  }
  const isEmpty = messages.length === 0 && !run;
  const titles: Record<string, string> = {
    chat: "مسار",
    library: "المكتبة المنشورة",
    "owner-library": "إدارة الملفات وتغطية المواد",
    models: "نماذج التدريس واختيار المراجع",
    usage: "الاستخدام والمحاسبة",
    security: "أمان الحساب",
    "service-tokens": "وصول الوكلاء",
    preferences: "تفضيلات وخصوصية",
    notes: "ملاحظات مسار التعليمية",
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
    <Button
      variant="outline"
      key={next}
      title={label}
      aria-label={accessible}
      aria-current={view === next ? "page" : undefined}
      className={view === next ? "active" : ""}
      onClick={() => navigate(next)}
    >
      <Icon name={icon} />
      <span>{label}</span>
    </Button>
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
  if (loading)
    return (
      <main className="loading">
        <Mark />
        <p>جارٍ فتح مسار…</p>
      </main>
    );
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
          <div className="auth-pill">
            <Icon name="practice" size={18} /> مساحة تعلّم للبكالوريا الجزائرية
          </div>
          <div className="auth-features">
            {[
              [
                "book",
                "تعلّم من المصدر",
                "دروس ومراجع منشورة، قريبة من سؤالك.",
              ],
              [
                "practice",
                "ابنِ الحل خطوة بخطوة",
                "فهم الفكرة، ثم التدريب على تطبيقها.",
              ],
              ["shield", "مساحتك تبقى لك", "محادثاتك وملاحظاتك في مكان واحد."],
            ].map(([icon, title, detail]) => (
              <div key={title}>
                <span className="auth-feature-icon">
                  <Icon name={icon as IconName} />
                </span>
                <div>
                  <strong>{title}</strong>
                  <p>{detail}</p>
                </div>
              </div>
            ))}
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
              <Input name="name" required autoComplete="name" />
            </label>
          )}
          <label>
            البريد الإلكتروني
            <Input
              name="email"
              type="email"
              dir="ltr"
              required
              autoComplete="username"
            />
          </label>
          <label>
            كلمة المرور
            <Input
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
          <Button variant="outline" className="primary" type="submit">
            {authMode === "login" ? "دخول" : "إنشاء حساب"}
          </Button>
          <Button
            variant="outline"
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
          </Button>
          <Button
            variant="outline"
            type="button"
            className="text-button"
            onClick={() => setRecovery("request")}
          >
            نسيت كلمة المرور أو تأكيد البريد؟
          </Button>
        </form>
      </main>
    );
  if (user.role === "student" && !user.study_track)
    return (
      <main className="auth-page">
        <form
          className="panel onboarding"
          onSubmit={(e) => {
            e.preventDefault();
            action(async () => {
              const d = await api("/api/auth/study-track", "PUT", {
                value: onboardingTrack,
              });
              setUser(d.user);
              setSubject("");
              await refreshChats();
            });
          }}
        >
          <div className="onboarding-brand">
            <Mark small />
            <strong>مسار</strong>
            <CountBadge>الخطوة الأولى</CountBadge>
          </div>
          <h1>اختر شعبتك الدراسية</h1>
          <p>
            هذا الاختيار إلزامي ويُحفظ مرة واحدة؛ لن تتمكن من تغييره لاحقًا.
            تأكد من شعبتك قبل التأكيد.
          </p>
          <label>
            الشعبة الدراسية
            <NativeSelect
              required
              aria-label="الشعبة الدراسية"
              value={onboardingTrack}
              onChange={(e) => setOnboardingTrack(e.target.value)}
            >
              <option value="">اختر الشعبة</option>
              {studyCatalog.tracks.map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label}
                </option>
              ))}
            </NativeSelect>
          </label>
          <Button
            variant="outline"
            className="primary"
            disabled={busy || !onboardingTrack}
          >
            تأكيد الشعبة نهائيًا
          </Button>
          {notice && <p role="alert">{notice}</p>}
          <Button
            variant="outline"
            type="button"
            onClick={() =>
              action(async () => {
                await api("/api/auth/logout", "POST", {});
                setUser(null);
              })
            }
          >
            تسجيل الخروج
          </Button>
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
          <Button
            variant="outline"
            className="brand"
            aria-label="مسار · المحادثة"
            onClick={() => navigate("chat")}
          >
            <Mark small />
            <div className="sidebar-brand-copy">
              <strong>مسار</strong>
              <small>خطوة أقرب إلى الفهم</small>
            </div>
          </Button>
          <Button
            variant="outline"
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
          </Button>
          <Button
            variant="outline"
            className="icon-button drawer-close"
            aria-label="إغلاق القائمة"
            onClick={() => setMenu(false)}
          >
            <Icon name="close" />
          </Button>
        </div>
        <nav aria-label="مساحة التعلّم" className="primary-nav">
          <Button
            variant="outline"
            className="new-chat"
            aria-label="＋ محادثة جديدة"
            title="محادثة جديدة"
            onClick={() => action(createChat)}
            disabled={busy}
          >
            <Icon name="write" />
            <span>محادثة جديدة</span>
            <kbd>جديد</kbd>
          </Button>
          {user.role !== "student" &&
            navItem("materials", "مساحة إعداد الأستاذ", "practice")}
        </nav>
        {user.role === "owner" && (
          <div className="workspace-navigation">
            <p className="nav-caption">مساحة الإدارة</p>
            <nav aria-label="إدارة المنصة">
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
            </nav>
          </div>
        )}
        <label className="chat-search">
          <Icon name="search" size={17} />
          <Input
            placeholder="ابحث في محادثاتك"
            aria-label="البحث في المحادثات"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        <div className="history-caption">
          محادثاتك <CountBadge>{chats.length}</CountBadge>
        </div>
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
              <Button
                variant="outline"
                aria-current={
                  c.id === chatId && view === "chat" ? "page" : undefined
                }
                onClick={() => action(() => openChat(c.id))}
                title={c.title}
              >
                {c.title}
              </Button>
              <details>
                <summary aria-label="خيارات المحادثة">
                  <Icon name="more" size={18} />
                </summary>
                <div className="history-actions">
                  <Button
                    variant="outline"
                    onClick={(e) => {
                      dialogReturnFocus.current =
                        e.currentTarget
                          .closest("details")
                          ?.querySelector<HTMLElement>("summary") || null;
                      e.currentTarget
                        .closest("details")
                        ?.removeAttribute("open");
                      setRenameTitle(c.title);
                      setChatDialog({ kind: "rename", chat: c });
                    }}
                  >
                    <Icon name="write" size={16} /> إعادة تسمية
                  </Button>
                  <Button
                    variant="outline"
                    className="destructive-text"
                    onClick={(e) => {
                      dialogReturnFocus.current =
                        e.currentTarget
                          .closest("details")
                          ?.querySelector<HTMLElement>("summary") || null;
                      e.currentTarget
                        .closest("details")
                        ?.removeAttribute("open");
                      setChatDialog({ kind: "delete", chat: c });
                    }}
                  >
                    <Icon name="trash" size={16} /> حذف
                  </Button>
                </div>
              </details>
            </div>
          ))}
        </div>
        <div className="profile" ref={accountRef}>
          <Button
            variant="outline"
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
            <span className="profile-action">
              <Icon name="settings" size={18} />
            </span>
          </Button>
          {
            <div
              id="account-panel"
              className={"account-panel " + (accountOpen ? "is-open" : "")}
              aria-hidden={!accountOpen}
              inert={!accountOpen}
              aria-label="إعدادات ومساحات الحساب"
            >
              <div className="account-summary">
                <span className="avatar">{user.name.trim().slice(0, 1)}</span>
                <div>
                  <strong>{user.name}</strong>
                  <small>إعدادات مساحتك الخاصة</small>
                </div>
              </div>
              <nav aria-label="إعدادات الحساب والتنقل">
                {navItem("preferences", "تفضيلات وخصوصية", "settings")}
                {navItem("notes", "ملاحظات مسار التعليمية", "note")}
                {navItem("security", "أمان الحساب", "shield")}
                {navItem("personal-usage", "استخدامي وحدودي", "chart")}
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
                  <Button
                    variant="outline"
                    key={value}
                    title={label}
                    aria-label={"مظهر " + label}
                    aria-pressed={appearance === value}
                    onClick={() => setAppearance(value)}
                  >
                    <Icon name={icon} size={17} />
                    <span>{label}</span>
                  </Button>
                ))}
              </div>
              <Button
                variant="outline"
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
              </Button>
            </div>
          }
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
            <Button
              variant="outline"
              className="icon-button menu-button"
              onClick={() => setMenu(!menu)}
              aria-label="فتح القائمة"
              aria-controls="conversation-sidebar"
              aria-expanded={menu}
            >
              <Icon name="menu" />
            </Button>
            <Button
              variant="outline"
              className="workspace-brand"
              aria-label="مسار · العودة للمحادثة"
              onClick={() => navigate("chat")}
            >
              {view === "chat" ? (
                <span className="workspace-wordmark">مسار</span>
              ) : (
                <WorkspaceHeading title={titles[view]} />
              )}
              {view === "chat" && (
                <span className="assistant-badge">مساعد التعلّم</span>
              )}
            </Button>
          </div>
          <div className="topbar-actions">
            {view === "chat" && user.role === "student" && (
              <SubjectPicker
                value={subject}
                disabled={busy}
                choices={allowedSubjects}
                onChange={chooseSubject}
              />
            )}
            <span
              className="chat-title"
              title={chats.find((c) => c.id === chatId)?.title}
            >
              {view === "chat"
                ? chats.find((c) => c.id === chatId)?.title || "محادثة جديدة"
                : "مساحة خاصة"}
            </span>
            <Button
              variant="outline"
              className="icon-button"
              title="محادثة جديدة"
              aria-label="بدء محادثة جديدة"
              onClick={() => action(createChat)}
              disabled={busy}
            >
              <Icon name="write" />
            </Button>
          </div>
        </header>
        {notice && (
          <div className="notice" role="status">
            <span>{notice}</span>
            <Button
              variant="outline"
              className="icon-button"
              onClick={() => setNotice("")}
              aria-label="إغلاق التنبيه"
            >
              <Icon name="close" size={18} />
            </Button>
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
                  <Welcome name={user.name} teacher={user.role === "teacher"} />
                ) : (
                  messages.map((m, index) => (
                    <React.Fragment key={m.id}>
                      <article className={"message " + m.role}>
                        {m.role === "assistant" && m.activity && (
                          <RunActivity
                            activity={m.activity}
                            open={Boolean(expandedRuns[m.activity.run_id])}
                            onToggle={() => toggleWork(m.activity!.run_id)}
                          />
                        )}
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
                              <Button
                                variant="outline"
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
                              </Button>
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
                                <Button
                                  variant="outline"
                                  className="icon-button"
                                  aria-label="إعادة محاولة الرسالة الأخيرة"
                                  title="إعادة محاولة الرسالة الأخيرة"
                                  onClick={retryAnswer}
                                  disabled={busy}
                                >
                                  <Icon name="retry" size={17} />
                                </Button>
                              )}
                            </>
                          )}
                        </div>
                      </article>
                      {m.role === "user" &&
                        m.previous_activities?.map((activity, attempt) => (
                          <article
                            key={activity.run_id}
                            className="message assistant historical-work"
                          >
                            <p className="work-caption">
                              محاولة سابقة {attempt + 1}
                            </p>
                            <RunActivity
                              activity={activity}
                              open={Boolean(expandedRuns[activity.run_id])}
                              onToggle={() => toggleWork(activity.run_id)}
                            />
                          </article>
                        ))}
                      {m.role === "user" &&
                        m.unanswered_activity &&
                        m.unanswered_activity.run_id !== run && (
                          <article className="message assistant pending-work">
                            <RunActivity
                              activity={m.unanswered_activity}
                              open={Boolean(
                                expandedRuns[m.unanswered_activity.run_id],
                              )}
                              onToggle={() =>
                                toggleWork(m.unanswered_activity!.run_id)
                              }
                            />
                            {!run &&
                              index === messages.length - 1 &&
                              ["unavailable", "cancelled"].includes(
                                m.unanswered_activity.status,
                              ) && (
                                <Button
                                  variant="outline"
                                  type="button"
                                  className="retry-work"
                                  onClick={retryAnswer}
                                  disabled={busy}
                                >
                                  <Icon name="retry" size={15} /> إعادة المحاولة
                                </Button>
                              )}
                          </article>
                        )}
                    </React.Fragment>
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
                {(run || activeActivity) && (
                  <article className="message assistant pending-work">
                    <RunActivity
                      activity={
                        activeActivity || {
                          run_id: run,
                          status: "queued",
                          items: [],
                        }
                      }
                      open={Boolean(
                        expandedRuns[activeActivity?.run_id || run],
                      )}
                      onToggle={() => toggleWork(activeActivity?.run_id || run)}
                    />
                  </article>
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
                <Button
                  variant="outline"
                  className="jump-latest"
                  aria-label="العودة إلى أحدث رسالة"
                  onClick={jumpToLatest}
                >
                  <Icon name="down" size={18} />
                </Button>
              )}
              {editing && (
                <div className="editing">
                  <span>تعديل الرسالة · سيُنشأ مسار جديد للردود التالية.</span>
                  <Button
                    variant="outline"
                    className="icon-button"
                    aria-label="إلغاء التعديل"
                    onClick={() => {
                      setEditing("");
                      setText("");
                    }}
                  >
                    <Icon name="close" size={17} />
                  </Button>
                </div>
              )}
              <form className="composer" onSubmit={send}>
                <Textarea
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
                      <Button
                        variant="outline"
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
                      </Button>
                    ) : (
                      <Button
                        variant="outline"
                        className="send-button"
                        aria-label="إرسال ↑"
                        title="إرسال"
                        disabled={busy || !text.trim() || needsSubject}
                      >
                        <Icon name="arrow" size={21} />
                      </Button>
                    )}
                  </div>
                </div>
              </form>
              <p className="composer-note">
                قد يخطئ مسار. تحقّق من المصادر والنتائج المهمة.
              </p>
            </div>
            {isEmpty && (
              <Starters
                items={starters}
                choose={(prompt) => {
                  setText(prompt);
                  composerInput.current?.focus();
                }}
              />
            )}
          </div>
        )}
        {view === "models" && (
          <section tabIndex={0} className="page-content narrow">
            <h1>نماذج التدريس واختيار المراجع</h1>
            <p className="muted">
              إعداد التدريس مستقل عن اختيار المراجع واستخراج الكتب. اختر مزوّدًا
              ليُضبط الرابط والبروتوكول والنموذج الافتراضي؛ أدخل المفتاح فقط،
              ويمكنك تغيير النموذج. الإعدادات الجديدة تخص تشغيلات جديدة،
              والمفاتيح محفوظة مشفرًا ولا تُعرض.
            </p>
            <form
              className="panel model-settings"
              onSubmit={(e) => {
                e.preventDefault();
                action(async () => {
                  const config: any = { ...model };
                  delete config.id;
                  delete config.slot;
                  delete config.key_saved;
                  delete config.router_requires_reconfiguration;
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
              <div className="section-heading">
                <h2>إعداد اتصال النموذج</h2>
                <CountBadge>إعدادات مشفّرة</CountBadge>
              </div>
              <label>
                الاستخدام
                <NativeSelect
                  value={slot}
                  onChange={(e) => {
                    const next = e.target.value;
                    setSlot(next);
                    setKey("");
                    setCatalog([]);
                    action(async () => {
                      const offered = (
                        await api("/api/owner/model-presets?slot=" + next)
                      ).items;
                      setProviderPresets(offered);
                      const saved = models.find((m) => m.slot === next);
                      const preset = offered.find(
                        (p: any) =>
                          p.id === (next === "selector" ? "google" : "openai"),
                      );
                      setModel(
                        saved || {
                          max_tokens:
                            preset.max_tokens ||
                            6000,
                          focused_mode: true,
                          timeout: 90,
                          max_context_chars: null,
                          main_max_rounds: 4,
                          selector_max_sources: 3,
                          input_price_per_million: null,
                          output_price_per_million: null,
                          cached_price_per_million: null,
                          provider: preset.id,
                          protocol: preset.protocol,
                          base_url: preset.base_url,
                          model: preset.model,
                          temperature: preset.temperature,
                          selector_enabled: false,
                        },
                      );
                    });
                  }}
                >
                  <option value="agent">وكيل التدريس</option>
                  <option value="selector">
                    راوتر المراجع — LLM بالفهرس الكامل
                  </option>
                </NativeSelect>
              </label>
              <label>
                المزوّد
                <NativeSelect
                  value={model.provider || "custom"}
                  onChange={(e) => {
                    const p = providerPresets.find(
                      (p) => p.id === e.target.value,
                    );
                    if (!p) return;
                    setModel({
                      ...model,
                      provider: p.id,
                      protocol: p.protocol,
                      base_url: p.base_url,
                      model: p.model,
                      temperature: p.temperature,
                      focused_mode: p.focused_mode ?? true,
                      max_tokens: p.max_tokens ?? model.max_tokens,
                      input_price_per_million: null,
                      output_price_per_million: null,
                      cached_price_per_million: null,
                    });
                    setKey("");
                    setCatalog([]);
                    setNotice(
                      "ضُبط القالب فقط؛ لم يُرسل أي طلب توليد. أدخل مفتاح المزوّد الجديد، والنموذج الافتراضي قابل للتغيير حسب إتاحة حسابك.",
                    );
                  }}
                >
                  {providerPresets.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <p className="muted">
                البروتوكول:{" "}
                {model.protocol === "anthropic"
                  ? "Anthropic Messages الأصلي"
                  : model.protocol === "google"
                    ? "Google GenerateContent الأصلي"
                    : "OpenAI-compatible Chat"}
              </p>
              {slot === "selector" && (
                <>
                  <label>
                    <input
                      type="checkbox"
                      checked={!!model.selector_enabled}
                      onChange={(e) =>
                        setModel({
                          ...model,
                          selector_enabled: e.target.checked,
                        })
                      }
                    />{" "}
                    تفعيل اختيار المراجع المنسّق للتشغيلات الجديدة
                  </label>
                  {model.router_requires_reconfiguration && (
                    <p className="notice">
                      إعداد الراوتر السابق لم يعد مدعومًا. اختر مزوّد LLM وأدخل
                      مفتاحه واحفظ؛ لن نعيد توجيه المفتاح القديم تلقائيًا.
                    </p>
                  )}
                  <label>
                    معرّف كتاب منشور — اختياري
                    <Input
                      dir="ltr"
                      value={model.selector_document_id || ""}
                      onChange={(e) =>
                        setModel({
                          ...model,
                          selector_document_id: e.target.value.trim() || null,
                        })
                      }
                    />
                  </label>
                  <p className="muted">
                    تركه فارغًا يعرض فهارس جميع المواد المنشورة. هذا المسار
                    يحتاج Google الأصلي أو OpenAI-compatible، ويجري قرارًا
                    بالفهرس ثم فحصًا للنصوص المقروءة. يزيد عدد الاستدعاءات؛ حفظ
                    الإعدادات لا يرسل طلب توليد. عند الغموض يسأل الطالب دون
                    توليد شرح.
                  </p>
                  <label>
                    سقف المراجع المختارة لكل طلب
                    <Input
                      type="number"
                      min={1}
                      max={8}
                      value={model.selector_max_sources || 3}
                      onChange={(e) =>
                        setModel({
                          ...model,
                          selector_max_sources: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <p className="muted">
                    المسار الوحيد: الفهرس الكامل ثم قراءة النصوص وفحصها. تجريبي:
                    حتى ثلاثة مراجع افتراضيًا، بسقف من 1 إلى 8. يختار أقل مجموعة
                    كافية لكل هدف، مع السماح بأجزاء مكملة مثل نص التمرين وحله.
                    يقرأ النصوص الفعلية ويفحصها قبل تسليمها؛ الفحص لا يضمن غياب
                    الأخطاء. الفهرس الكبير يخضع لحصة الرموز لدى المزوّد، ولا
                    يوجد رجوع تلقائي لنموذج آخر.
                  </p>
                </>
              )}
              <label>
                Base URL
                <Input
                  type="url"
                  dir="ltr"
                  required
                  value={model.base_url}
                  readOnly={!!model.provider && model.provider !== "custom"}
                  onChange={(e) =>
                    setModel({ ...model, base_url: e.target.value })
                  }
                />
              </label>
              {(!model.provider || model.provider === "custom") && (
                <label>
                  بروتوكول المزوّد المخصص
                  <NativeSelect
                    value={model.protocol || "openai"}
                    onChange={(e) => {
                      setModel({ ...model, protocol: e.target.value });
                      setKey("");
                    }}
                  >
                    {slot === "selector" && (
                      <option value="google">
                        Google GenerateContent / LLM
                      </option>
                    )}
                    <option value="openai">OpenAI-compatible</option>
                    {slot !== "selector" && (
                      <option value="anthropic">Anthropic Messages</option>
                    )}
                  </NativeSelect>
                </label>
              )}
              <label>
                Model
                <Input
                  dir="ltr"
                  required
                  value={model.model}
                  list="provider-model-list"
                  onChange={(e) =>
                    setModel({ ...model, model: e.target.value })
                  }
                />
              </label>
              <datalist id="provider-model-list">
                {catalog
                  .filter((m) => slot !== "selector" || m.type !== "evaluation")
                  .map((m) => (
                    <option key={m.id} value={m.id} />
                  ))}
              </datalist>
              <label>
                API Key
                <Input
                  type="password"
                  autoComplete="off"
                  dir="ltr"
                  value={key}
                  placeholder={
                    model.router_requires_reconfiguration
                      ? "أدخل مفتاح المزوّد الجديد؛ المفتاح القديم لن يُستخدم"
                      : models.some((m) => m.slot === slot)
                        ? "مفتاح محفوظ — اترك الحقل فارغًا للاحتفاظ به"
                        : "أدخل المفتاح؛ لا يُضمّن في المتصفح أو Git"
                  }
                  onChange={(e) => setKey(e.target.value)}
                />
              </label>
              {slot === "agent" && (
                <label>
                  <input
                    type="checkbox"
                    checked={model.focused_mode !== false}
                    onChange={(e) =>
                      setModel({ ...model, focused_mode: e.target.checked })
                    }
                  />
                  نمط الإجابة المنضبطة
                  <span className="muted">
                    يخفض العشوائية إلى 0.1 أو أقل، وليس زيادةً للتفكير أو ضمانًا
                    للصحة. عطّله إن كان نموذجك يتطلب Temperature خاصًا.
                  </span>
                </label>
              )}
              {slot !== "extraction" && (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() =>
                      setModel({
                        ...model,
                        max_tokens: Math.max(model.max_tokens || 0, 6000),
                        temperature: slot === "selector" ? 0 : 0.1,
                        focused_mode: true,
                      })
                    }
                  >
                    ضبط موصى به: إخراج 6000 وإجابة منضبطة
                  </Button>
                  <p className="muted">
                    6000 حدّ أعلى متاح للتوليد، لا عدد رموز يُستهلك تلقائيًا.
                    {slot === "selector"
                      ? " الراوتر يستخدم عشوائية 0، ووصف الهدف محدود بـ400 حرف."
                      : model.focused_mode !== false
                        ? ` Temperature الفعلي: ${Math.min(model.temperature ?? 0.1, 0.1)}.`
                        : " يُستخدم Temperature الذي تختاره دون خفضه."}
                  </p>
                </>
              )}
              <div className="form-columns">
                <label>
                  عشوائية الإجابة (Temperature)
                  <Input
                    type="number"
                    min="0"
                    max="2"
                    step="0.1"
                    disabled={slot === "selector"}
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
                  <Input
                    type="number"
                    min="6000"
                    max="32000"
                    value={model.max_tokens}
                    onChange={(e) =>
                      setModel({ ...model, max_tokens: Number(e.target.value) })
                    }
                  />
                </label>
              </div>
              {slot === "agent" && (
                <details>
                  <summary>السياق وجولات الأدوات</summary>
                  <label>
                    ميزانية السياق بالحروف — حسب قدرة النموذج
                    <Input
                      type="number"
                      min="10000"
                      max="4000000"
                      value={model.max_context_chars ?? ""}
                      placeholder="الحد الافتراضي للخادم"
                      onChange={(e) =>
                        setModel({
                          ...model,
                          max_context_chars:
                            e.target.value === ""
                              ? null
                              : Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <label>
                    جولات النموذج عند تفعيل المنسّق
                    <Input
                      type="number"
                      min="2"
                      max="8"
                      value={model.main_max_rounds ?? 4}
                      onChange={(e) =>
                        setModel({
                          ...model,
                          main_max_rounds: Number(e.target.value),
                        })
                      }
                    />
                  </label>
                  <p className="muted">
                    المنسّق يجلب المحتوى كاملًا دون حد نتيجة قراءة الأداة
                    القديم. ميزانية السياق مستقلة وقابلة للزيادة؛ لا يحدث قصّ
                    صامت. الرجوع للمراجع مسموح لإضافة أساسية واحدة فقط.
                  </p>
                </details>
              )}
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
                    <Input
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
              <Button
                variant="outline"
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
                      setCatalog(r.models || []);
                      setNotice(
                        r.connected
                          ? (r.model_advertised
                              ? "الاتصال نجح والنموذج موجود في قائمة المزوّد."
                              : "الاتصال نجح، لكن الاسم المحفوظ لم يظهر في قائمة المزوّد؛ راجع الاسم والإتاحة.") +
                              " هذا فحص اتصال فقط، وليس اختبار توليد أو رؤية أو أدوات."
                          : "تعذر الاتصال",
                      );
                    });
                }}
              >
                اختبار الاتصال المحفوظ
              </Button>
              <Button variant="outline" className="primary" disabled={busy}>
                حفظ الإعداد
              </Button>
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
          <OwnerLibrary api={api} catalogue={studyCatalog} notify={setNotice} render={text => <Md text={text} />} />
        )}
        {view === "usage" && (
          <section tabIndex={0} className="page-content">
            <h1>استخدام معلَن، لا تقديرات وهمية</h1>
            <p className="muted">
              تُحفظ الأرقام التي يعيدها المزوّد فقط. التكلفة لا تتوفر دون أسعار
              مهيّأة؛ Cache غير المبلّغ عنه يظهر كغير متاح.
            </p>
            {usage && (
              <>
                <UsageSummary data={usage} />
                <p>طلبات بلا بيانات استخدام: {usage.missing_usage_calls}</p>
                <p>
                  المحاسبة آخر {usage.days} يومًا. بيانات Cache والأسعار
                  المفقودة ليست صفرًا؛ مجموعات جزئية تُعرض أدناه.
                </p>
                <details className="usage-details">
                  <summary>تفاصيل المحاسبة والبيانات الناقصة</summary>
                  <pre tabIndex={0} className="material-solution" dir="ltr">
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
                </details>
                <div
                  tabIndex={0}
                  role="region"
                  aria-label="جدول قابل للتمرير"
                  className="table-scroll"
                >
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
          returnFocus={dialogReturnFocus.current}
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
                <Input
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
              <Button
                variant="outline"
                className={
                  chatDialog.kind === "delete" ? "danger-button" : "primary"
                }
                disabled={
                  busy || (chatDialog.kind === "rename" && !renameTitle.trim())
                }
              >
                {chatDialog.kind === "rename" ? "حفظ العنوان" : "حذف نهائيًا"}
              </Button>
              <Button
                variant="outline"
                type="button"
                onClick={() => setChatDialog(null)}
              >
                إلغاء
              </Button>
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
              <Button
                variant="outline"
                onClick={() => setSource(null)}
                aria-label="إغلاق المصدر"
              >
                ×
              </Button>
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
                  <Button
                    variant="outline"
                    className="node-row"
                    key={p.id}
                    onClick={() => readPart(p.id)}
                  >
                    جزء {p.part_index + 1} · {p.metadata.title} · ص{" "}
                    {p.metadata.pages.join("، ")}
                  </Button>
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
                <Button
                  variant="outline"
                  className="node-row"
                  key={n.id}
                  onClick={() => readSource(n.id)}
                >
                  {n.kind} · {n.title} · ص{" "}
                  <bdi dir="ltr">
                    {n.start_page}–{n.end_page}
                  </bdi>
                </Button>
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
createRoot(document.getElementById("root")!).render(
  <DesignProvider>
    <TooltipProvider delayDuration={400}>
      <App />
    </TooltipProvider>
  </DesignProvider>,
);
