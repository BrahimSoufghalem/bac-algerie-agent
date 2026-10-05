import React from "react";
import { Activity, CalendarDays, Info } from "lucide-react";
import { Card } from "./components/ui/card";
export function UsageSummary({ data }: { data: any }) {
  const items = [
    {
      icon: Activity,
      label: "جلسات التشغيل",
      value: data?.runs?.total,
      suffix: "جلسة مسجّلة",
    },
    {
      icon: CalendarDays,
      label: "فترة التقرير",
      value: data?.days,
      suffix: "يومًا",
    },
    {
      icon: Info,
      label: "طلبات ببيانات رموز ناقصة",
      value: data?.missing_usage_calls,
      suffix: "طلبًا",
    },
  ];
  return (
    <div className="usage-cards">
      {items.map(({ icon: Icon, label, value, suffix }) => (
        <Card key={label} className="usage-card">
          <div>
            <span>{label}</span>
            <Icon size={20} aria-hidden="true" />
          </div>
          <strong>
            {value == null ? "غير متاح" : value.toLocaleString("ar-DZ")}
          </strong>
          <small>{suffix}</small>
        </Card>
      ))}
    </div>
  );
}
export function UsageLimits({ data }: { data: any }) {
  const labels: Record<string, string> = {
    daily_limit: "عدد الرسائل اليومي",
    daily_tokens: "حد الرموز اليومي",
    messages_per_minute: "الرسائل في الدقيقة",
    max_active_runs: "التشغيلات المتزامنة",
    budget_alert: "عتبة تنبيه التكلفة",
  };
  if (!data?.limits) return null;
  return (
    <Card className="panel usage-limits">
      <h2>حدود حسابك</h2>
      <dl>
        {Object.entries(labels).map(([key, label]) => (
          <div key={key}>
            <dt>{label}</dt>
            <dd>
              {data.limits[key] == null
                ? "غير محدّد"
                : data.limits[key].toLocaleString("ar-DZ")}
            </dd>
          </div>
        ))}
      </dl>
      <p className="muted">
        يحدد المالك هذه الحدود. عتبة التكلفة تنبيه تقديري، وليست فاتورة نهائية.
      </p>
    </Card>
  );
}
export function UsageDetails({ data }: { data: any }) {
  return (
    <details className="usage-details">
      <summary>تفاصيل التقرير والبيانات المبلّغ عنها</summary>
      <pre tabIndex={0} className="material-solution" dir="ltr">
        {data ? JSON.stringify(data, null, 2) : "جارٍ التحميل…"}
      </pre>
    </details>
  );
}
