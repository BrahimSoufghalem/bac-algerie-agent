import { Button } from "./components/ui/button";
import React, { useId } from "react";
import { Icon, type IconName } from "./ChatUI";

export type WorkActivity = {
  run_id: string;
  status: "queued" | "running" | "completed" | "unavailable" | "cancelled";
  items: { id: string; kind: string; label: string; state: string }[];
};
const icons: Record<string, IconName> = {
  prepare: "chat",
  review: "search",
  math: "chart",
  check: "check",
  diagram: "chart",
  organize: "note",
  complete: "check",
};
export function RunActivity({
  activity,
  open,
  onToggle,
}: {
  activity: WorkActivity;
  open: boolean;
  onToggle: () => void;
}) {
  const id = useId();
  const active = activity.status === "queued" || activity.status === "running";
  const label = active
    ? "جارٍ إعداد الرد"
    : activity.status === "completed"
      ? "مراحل الإجابة"
      : "مراحل الطلب";
  const current = [...activity.items]
    .reverse()
    .find((x) => x.state === "running");
  return (
    <section
      className={
        "work-disclosure " +
        (open ? "is-open " : "") +
        (active ? "is-running" : "")
      }
      data-run={activity.run_id}
      aria-label="ملخص مراحل العمل"
    >
      <Button
        variant="outline"
        type="button"
        className="work-toggle"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
      >
        <span className={"work-emblem " + (active ? "work-breath" : "")}>
          <Icon name={active ? "retry" : "check"} size={15} />
        </span>
        <span className="work-toggle-title">{label}</span>
        <span className="work-toggle-detail">
          {active
            ? current?.label || "انتظار البدء"
            : `${activity.items.length} مراحل`}
        </span>
        <Icon name="chevron" size={16} />
      </Button>
      <div id={id} className="work-reveal" aria-hidden={!open} inert={!open}>
        <div className="work-reveal-inner">
          <p className="work-caption">
            ملخّص التقدّم والتنفيذ، وليس التفكير الداخلي.
          </p>
          <ol className="work-timeline">
            {activity.items.map((item) => (
              <li key={item.id} data-state={item.state}>
                <span className="work-node">
                  <Icon name={icons[item.kind] || "note"} size={14} />
                </span>
                <span className="work-step-label">{item.label}</span>
                <span className="work-step-state">
                  {item.state === "running" ? (
                    <span className="work-dots" aria-label="جارٍ" />
                  ) : item.state === "done" ? (
                    <Icon name="check" size={13} />
                  ) : (
                    <span className="work-not-complete">
                      {item.state === "stopped" ? "توقفت" : "تحتاج مراجعة"}
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ol>
          {activity.status === "completed" && (
            <p className="work-footnote">
              اكتمال المراحل لا يعني تصديقًا على كل الشرح.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
