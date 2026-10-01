import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

// Original, inline vector icons: no external requests, icon font or brand assets.
const paths = {
  panel: "M8 4v16M4 4h16v16H4zM12 8h4M12 12h4",
  menu: "M4 6h16M4 12h16M4 18h16",
  close: "m6 6 12 12M6 18 18 6",
  plus: "M12 5v14M5 12h14",
  write: "m14 5 5 5M4 20l4-1L20 7a2 2 0 0 0-4-4L4 15z",
  search: "M10 17a7 7 0 1 0 0-14 7 7 0 0 0 0 14Zm5-2 6 6",
  book: "M12 5v15M12 5C9 3 5 3 3 4v15c3-1 6-1 9 1 3-2 6-2 9-1V4c-3-1-6-1-9 1Z",
  chat: "M21 11a9 9 0 0 1-9 9H4l-2 2V11a9 9 0 1 1 19 0Z",
  note: "M5 3h14v18H5zM8 7h8M8 11h8M8 15h5",
  practice: "m12 3 10 5-10 5L2 8zM6 10v7c4 3 8 3 12 0v-7M22 8v9",
  more: "M5 12h.01M12 12h.01M19 12h.01",
  chevron: "m7 10 5 5 5-5",
  arrow: "M12 19V5m-6 6 6-6 6 6",
  down: "M12 5v14m-6-6 6 6 6-6",
  copy: "M9 9h12v12H9zM15 5V3H3v12h2",
  check: "m5 12 4 4 10-10",
  retry: "M4 8a8 8 0 1 1-1 7M4 3v5h5",
  attach: "m8 12 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9M6 14l8-8",
  stop: "M6 6h12v12H6z",
  shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM9 12l2 2 4-4",
  settings:
    "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2",
  sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8ZM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1 1M18 18l1 1M5 19l1-1M18 6l1-1",
  moon: "M20 14A9 9 0 0 1 10 3a9 9 0 1 0 10 11Z",
  monitor: "M3 4h18v13H3zM8 21h8M12 17v4",
  logout: "M9 3H3v18h6M8 12h13m-5-5 5 5-5 5",
  chart: "M4 3v17h17M8 16v-5M13 16V7M18 16V4",
  users:
    "M8 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8ZM2 21v-3a6 6 0 0 1 12 0v3M16 4a4 4 0 0 1 0 8M17 15a5 5 0 0 1 5 5",
  key: "M8 14a6 6 0 1 0 0-12 6 6 0 0 0 0 12Zm4-4 9 9v3h-3v-3h-3v-3",
  trash: "M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7",
} as const;
export type IconName = keyof typeof paths;
export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="ui-icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.65}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}
export function Mark({ small = false }: { small?: boolean }) {
  return (
    <svg
      className={small ? "masar-mark small" : "masar-mark"}
      viewBox="0 0 48 48"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M10 33V18a8 8 0 0 1 16 0v15a6 6 0 0 0 12 0V14"
        stroke="currentColor"
        strokeWidth="4"
        strokeLinecap="round"
      />
      <path
        d="m33 18 5-5 5 5"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}
export type Appearance = "system" | "light" | "dark";
function stored(name: string, fallback: string) {
  try {
    return localStorage.getItem(name) || fallback;
  } catch {
    return fallback;
  }
}
export function useAppearance() {
  const [appearance, setAppearance] = useState<Appearance>(() => {
    const value = stored("masar-appearance", "system");
    return ["light", "dark", "system"].includes(value)
      ? (value as Appearance)
      : "system";
  });
  useLayoutEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const update = () => {
      document.documentElement.dataset.theme =
        appearance === "system"
          ? media.matches
            ? "dark"
            : "light"
          : appearance;
    };
    update();
    try {
      localStorage.setItem("masar-appearance", appearance);
    } catch {
      /* Storage may be disabled. */
    }
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, [appearance]);
  return { appearance, setAppearance };
}
export function useSidebar() {
  const [collapsed, setCollapsed] = useState(
    () => stored("masar-sidebar", "open") === "collapsed",
  );
  useEffect(() => {
    try {
      localStorage.setItem("masar-sidebar", collapsed ? "collapsed" : "open");
    } catch {
      /* Non-essential preference. */
    }
  }, [collapsed]);
  return { collapsed, setCollapsed };
}
export function Dialog({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    const controls = () =>
      [
        ...(ref.current?.querySelectorAll<HTMLElement>("button, input") || []),
      ].filter((x) => !x.hasAttribute("disabled"));
    (controls().find((x) => x.tagName === "INPUT") || controls()[0])?.focus();
    const handle = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
      if (e.key === "Tab") {
        const a = controls(),
          first = a[0],
          last = a[a.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("keydown", handle);
      if (before?.isConnected) before.focus();
    };
  }, []);
  return (
    <div
      className="confirm-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <div
        className="confirm-dialog"
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="section-heading">
          <h2>{title}</h2>
          <button
            type="button"
            className="icon-button"
            aria-label="إغلاق النافذة"
            onClick={close}
          >
            <Icon name="close" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
export function CopyAnswer({
  text,
  notify,
}: {
  text: string;
  notify: (s: string) => void;
}) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (copied) {
      const t = setTimeout(() => setCopied(false), 1800);
      return () => clearTimeout(t);
    }
  }, [copied]);
  return (
    <button
      className="icon-button"
      aria-label={copied ? "تم نسخ الرد" : "نسخ الرد"}
      title={copied ? "تم النسخ" : "نسخ الرد"}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
        } catch {
          notify("تعذّر النسخ تلقائيًا. يمكنك تحديد نص الرد ونسخه.");
        }
      }}
    >
      <Icon name={copied ? "check" : "copy"} />
    </button>
  );
}
