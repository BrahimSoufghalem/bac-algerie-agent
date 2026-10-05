import React, { useState, useEffect } from "react";
import {
  LazyMotion,
  domAnimation,
  m,
  MotionConfig,
  useReducedMotion,
} from "motion/react";
import {
  BookOpen,
  ArrowLeft,
  LibraryBig,
  ListChecks,
  ShieldCheck,
} from "lucide-react";
import { Mark, type IconName, Icon } from "./ChatUI";
import { Button } from "./components/ui/button";
import { Badge } from "./components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "./components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "./components/ui/tooltip";
export function DesignProvider({ children }: { children: React.ReactNode }) {
  return (
    <MotionConfig reducedMotion="user">
      <LazyMotion features={domAnimation}>{children}</LazyMotion>
    </MotionConfig>
  );
}
export function Welcome({ name, teacher }: { name: string; teacher: boolean }) {
  const reduceMotion = useReducedMotion();
  return (
    <m.div
      className="welcome"
      initial={reduceMotion ? false : { opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: reduceMotion ? 0 : 0.25 }}
    >
      <div className="welcome-emblem">
        <Mark />
      </div>
      <p className="welcome-greeting">
        أهلًا {name.split(" ")[0]} <span aria-hidden="true">،</span> هذه مساحتك
        للفهم
      </p>
      <h1>
        {teacher ? "ما الذي نحضّره اليوم؟" : "ما الذي تريد أن تفهمه اليوم؟"}
      </h1>
      <p className="welcome-caption">
        ابدأ بسؤال صغير. نبني الفكرة والحل معًا، خطوة بخطوة.
      </p>
    </m.div>
  );
}
export function SubjectPicker({
  value,
  disabled,
  choices,
  onChange,
}: {
  value: string;
  disabled: boolean;
  choices: { id: string; label: string }[];
  onChange: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const root = document.getElementById("root");
    if (root) root.inert = open;
    return () => {
      if (root) root.inert = false;
    };
  }, [open]);
  return (
    <div className="subject-picker">
      <span className="subject-caption">المادة</span>
      <Select
        open={open}
        onOpenChange={setOpen}
        dir="rtl"
        value={value}
        onValueChange={onChange}
        disabled={disabled}
      >
        <SelectTrigger aria-label="مادة المحادثة" className="subject-trigger">
          <BookOpen aria-hidden="true" size={18} />
          <SelectValue placeholder="اختر المادة" />
        </SelectTrigger>
        <SelectContent position="popper" dir="rtl">
          {choices.map((q) => (
            <SelectItem key={q.id} value={q.id}>
              {q.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
export function Starters({
  items,
  choose,
}: {
  items: { icon: IconName; label: string; prompt: string }[];
  choose: (prompt: string) => void;
}) {
  const descriptions = [
    "ابدأ من الفكرة الأساسية",
    "افهم الخطوات، لا تحفظها",
    "اربط المعنى بالتطبيق",
  ];
  return (
    <div className="starter-bar" aria-label="طرق بدء التعلّم">
      {items.map((s, i) => (
        <Button
          key={s.label}
          variant="outline"
          aria-label={s.label}
          onClick={() => choose(s.prompt)}
        >
          <span className="starter-icon">
            <Icon name={s.icon} />
          </span>
          <span className="starter-copy">
            <strong>{s.label}</strong>
            <small>{descriptions[i]}</small>
          </span>
          <ArrowLeft className="starter-arrow" size={16} aria-hidden="true" />
        </Button>
      ))}
    </div>
  );
}
export function WorkspaceHeading({ title }: { title: string }) {
  return (
    <div className="workspace-heading">
      <span className="workspace-eyebrow">مسار / مساحتك</span>
      <span>{title}</span>
    </div>
  );
}
export function ContentWorkflow() {
  return (
    <ol className="content-workflow" aria-label="مراحل إعداد المحتوى">
      {[
        [LibraryBig, "ارفع المصدر"],
        [ListChecks, "استخرج وراجع"],
        [ShieldCheck, "اعتمد وانشر"],
      ].map(([I, title], i) => {
        const C = I as typeof LibraryBig;
        return (
          <li key={i}>
            <span className="workflow-number">{i + 1}</span>
            <C size={18} aria-hidden="true" />
            <span>{title as string}</span>
          </li>
        );
      })}
    </ol>
  );
}
export function Hint({
  label,
  children,
}: {
  label: string;
  children: React.ReactElement;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side="top" dir="rtl">
        {label}
      </TooltipContent>
    </Tooltip>
  );
}
export function CountBadge({ children }: { children: React.ReactNode }) {
  return (
    <Badge variant="secondary" className="count-badge">
      {children}
    </Badge>
  );
}
