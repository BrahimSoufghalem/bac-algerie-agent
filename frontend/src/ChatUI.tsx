import { Button } from "./components/ui/button";
import React, { useEffect, useLayoutEffect, useRef, useState } from "react";

import {
  PanelRight,
  Menu,
  X,
  Plus,
  SquarePen,
  Search,
  BookOpen,
  MessageSquare,
  StickyNote,
  GraduationCap,
  Ellipsis,
  ChevronDown,
  ArrowUp,
  ArrowDown,
  Copy,
  Check,
  RotateCcw,
  Paperclip,
  Square,
  ShieldCheck,
  Settings2,
  Sun,
  Moon,
  Monitor,
  LogOut,
  ChartNoAxesColumnIncreasing,
  Users,
  KeyRound,
  Trash2,
} from "lucide-react";
import {
  Dialog as DialogRoot,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "./components/ui/dialog";
const icons = {
  panel: PanelRight,
  menu: Menu,
  close: X,
  plus: Plus,
  write: SquarePen,
  search: Search,
  book: BookOpen,
  chat: MessageSquare,
  note: StickyNote,
  practice: GraduationCap,
  more: Ellipsis,
  chevron: ChevronDown,
  arrow: ArrowUp,
  down: ArrowDown,
  copy: Copy,
  check: Check,
  retry: RotateCcw,
  attach: Paperclip,
  stop: Square,
  shield: ShieldCheck,
  settings: Settings2,
  sun: Sun,
  moon: Moon,
  monitor: Monitor,
  logout: LogOut,
  chart: ChartNoAxesColumnIncreasing,
  users: Users,
  key: KeyRound,
  trash: Trash2,
} as const;
export type IconName = keyof typeof icons;
export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  const Component = icons[name];
  return (
    <Component
      className="ui-icon"
      size={size}
      strokeWidth={1.75}
      aria-hidden="true"
    />
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
  returnFocus,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
  returnFocus?: HTMLElement | null;
}) {
  const previous = useRef<HTMLElement | null>(
    returnFocus || (document.activeElement as HTMLElement | null),
  );
  useEffect(() => {
    const root = document.getElementById("root");
    if (root) root.inert = true;
    return () => {
      if (root) root.inert = false;
    };
  }, []);
  return (
    <DialogRoot
      open
      onOpenChange={(open) => {
        if (!open) close();
      }}
    >
      <DialogContent
        className="confirm-dialog"
        dir="rtl"
        onOpenAutoFocus={(e) => {
          const input = (
            e.currentTarget as HTMLElement
          ).querySelector<HTMLInputElement>("input:not([disabled])");
          if (input) {
            e.preventDefault();
            input.focus();
          }
        }}
        onCloseAutoFocus={(e) => {
          e.preventDefault();
          const root = document.getElementById("root");
          if (root) root.inert = false;
          requestAnimationFrame(() => {
            const visible = (el: HTMLElement | null): el is HTMLElement => {
              if (
                !el?.isConnected ||
                el === document.body ||
                !el.getClientRects().length ||
                getComputedStyle(el).visibility !== "visible" ||
                el.closest("[inert]")
              )
                return false;
              const r = el.getBoundingClientRect();
              return (
                r.right > 0 &&
                r.left < innerWidth &&
                r.bottom > 0 &&
                r.top < innerHeight
              );
            };
            const target = visible(previous.current)
              ? previous.current
              : [".menu-button", ".composer textarea", "#workspace-content"]
                  .map((s) => document.querySelector<HTMLElement>(s))
                  .find(visible);
            target?.focus();
          });
        }}
      >
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription className="sr-only">
            راجع البيانات قبل تأكيد الإجراء. يمكنك الإلغاء أو إغلاق النافذة.
          </DialogDescription>
        </DialogHeader>
        {children}
      </DialogContent>
    </DialogRoot>
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
    <Button
      variant="outline"
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
    </Button>
  );
}
