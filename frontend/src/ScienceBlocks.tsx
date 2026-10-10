import React, { useId, useMemo, useRef, useState, useEffect } from "react";
export type ScientificResult = {
  result_id: string;
  tool: string;
  inputs: Record<string, unknown>;
  output: {
    status: string;
    scope?: string;
    origin?: string;
    expression?: string;
    exact?: string;
    decimal?: string;
    value?: string;
    unit?: string;
    result?: string;
    actual?: { decimal: string };
    expected?: { decimal: string };
    absolute_error?: string;
    effective_tolerance?: string;
    reason?: string;
    outputs?: Record<string, unknown>;
    conditions?: {
      condition: { lhs: string; relation: string; rhs: string };
      passed: boolean;
    }[];
    chart?: Chart;
    [key: string]: unknown;
  };
};
type Series = { label: string; x: number[]; y: (number | null)[] };
type Chart = {
  title: string;
  x_label: string;
  y_label: string;
  kind: "line" | "scatter" | "bar";
  series: Series[];
};
const colors = ["#215db0", "#198064", "#8057ae", "#b57b16"];
function format(x: number) {
  return new Intl.NumberFormat("en", {
    maximumSignificantDigits: 5,
    notation:
      Math.abs(x) >= 1e6 || (Math.abs(x) > 0 && Math.abs(x) < 1e-4)
        ? "scientific"
        : "standard",
  }).format(x);
}
export function ScientificChart({ result }: { result: ScientificResult }) {
  const chart = result.output.chart;
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640),
    [selected, setSelected] = useState(0);
  const titleId = useId(),
    descriptionId = useId();
  useEffect(() => {
    const observer = new ResizeObserver((entries) =>
      setWidth(Math.max(280, Math.min(900, entries[0].contentRect.width))),
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  const points = useMemo(
    () =>
      chart?.series.flatMap((s, j) =>
        s.x.map((x, i) => ({ x, y: s.y[i], label: s.label, color: colors[j] })),
      ) || [],
    [chart],
  );
  if (
    !chart ||
    !points.length ||
    !points.every(
      (p) => Number.isFinite(p.x) && (p.y === null || Number.isFinite(p.y)),
    )
  )
    return <p className="error">بيانات الرسم غير صالحة؛ لم تُعرض.</p>;
  const xs = points.map((p) => p.x),
    ys = points.flatMap((p) => (p.y === null ? [] : [p.y]));
  if (!ys.length) return <p>لا توجد نقاط حقيقية للرسم.</p>;
  let xmin = Math.min(...xs),
    xmax = Math.max(...xs),
    ymin = Math.min(...ys),
    ymax = Math.max(...ys);
  if (chart.kind === "bar") {
    ymin = Math.min(0, ymin);
    ymax = Math.max(0, ymax);
  }
  if (xmin === xmax) {
    const delta = Math.max(1, Math.abs(xmin) * 0.1);
    xmin -= delta;
    xmax += delta;
  }
  if (ymin === ymax) {
    ymin -= Math.max(1, Math.abs(ymin) * 0.1);
    ymax += Math.max(1, Math.abs(ymax) * 0.1);
  }
  const height = width < 500 ? 300 : 370,
    left = 65,
    right = width - 20,
    top = 22,
    bottom = height - 65;
  const X = (x: number) => left + ((x - xmin) / (xmax - xmin)) * (right - left);
  const Y = (y: number) =>
    bottom - ((y - ymin) / (ymax - ymin)) * (bottom - top);
  const distinctX = [...new Set(xs)].sort((a, b) => a - b);
  const minimumXGap = Math.min(
    ...distinctX.slice(1).map((x, i) => x - distinctX[i]),
  );
  const barGroupWidth = Math.min(
    36,
    (Number.isFinite(minimumXGap)
      ? (minimumXGap / (xmax - xmin)) * (right - left)
      : 36) * 0.7,
  );
  const barWidth = barGroupWidth / chart.series.length;
  const current = points[Math.min(selected, points.length - 1)];
  const nearest = (e: React.PointerEvent<SVGSVGElement>) => {
    const box = e.currentTarget.getBoundingClientRect();
    const x =
      xmin +
      ((((e.clientX - box.left) / box.width) * width - left) / (right - left)) *
        (xmax - xmin);
    let best = 0;
    points.forEach((p, i) => {
      if (Math.abs(p.x - x) < Math.abs(points[best].x - x)) best = i;
    });
    setSelected(best);
  };
  return (
    <figure className="scientific-chart" ref={ref} aria-label="رسم علمي تفاعلي">
      <figcaption>
        <strong>{chart.title}</strong>
        <span className="muted">
          {result.output.origin === "sampled_function"
            ? "منحنى محسوب عيّنيًا"
            : ["computed_program_outputs", "executed_python"].includes(result.output.origin || "")
              ? "من المخرجات المحسوبة مباشرة"
              : "بيانات مقدّمة — لم يُؤكّد مصدرها"}
        </span>
      </figcaption>
      <div className="chart-legend">
        {chart.series.map((s, i) => (
          <span key={i}>
            <i style={{ background: colors[i] }} />
            {s.label}
          </span>
        ))}
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-labelledby={`${titleId} ${descriptionId}`}
        onPointerMove={nearest}
        style={{ direction: "ltr" }}
      >
        <title id={titleId}>{chart.title}</title>
        <desc id={descriptionId}>
          {chart.x_label} مقابل {chart.y_label}. القيم الكاملة متاحة أسفل الرسم،
          والفجوات لا توصل بخط.
        </desc>
        {[0, 1, 2, 3, 4].map((i) => {
          const y = ymin + ((ymax - ymin) * i) / 4;
          return (
            <g key={i}>
              <line x1={left} x2={right} y1={Y(y)} y2={Y(y)} stroke="#e1e5ed" />
              <text x={left - 9} y={Y(y) + 4} textAnchor="end">
                {format(y)}
              </text>
            </g>
          );
        })}
        {[0, 1, 2, 3, 4].map((i) => {
          const x = xmin + ((xmax - xmin) * i) / 4;
          return (
            <text key={i} x={X(x)} y={bottom + 23} textAnchor="middle">
              {format(x)}
            </text>
          );
        })}
        <line x1={left} x2={left} y1={top} y2={bottom} stroke="#727d90" />
        <line x1={left} x2={right} y1={bottom} y2={bottom} stroke="#727d90" />
        {ymin < 0 && ymax > 0 && (
          <line
            x1={left}
            x2={right}
            y1={Y(0)}
            y2={Y(0)}
            stroke="#727d90"
            strokeDasharray="4 4"
          />
        )}
        <text
          x={(left + right) / 2}
          y={height - 13}
          textAnchor="middle"
          className="axis-label"
        >
          {chart.x_label}
        </text>
        <text
          x="16"
          y={(top + bottom) / 2}
          textAnchor="middle"
          transform={`rotate(-90 16 ${(top + bottom) / 2})`}
          className="axis-label"
        >
          {chart.y_label}
        </text>
        {chart.series.map((s, j) => {
          const path = s.x
            .map((x, i) =>
              s.y[i] === null
                ? ""
                : `${i === 0 || s.y[i - 1] === null ? "M" : "L"}${X(x)},${Y(s.y[i]!)}`,
            )
            .join(" ");
          return (
            <g key={j}>
              {chart.kind === "line" && (
                <path
                  d={path}
                  fill="none"
                  stroke={colors[j]}
                  strokeWidth="2.5"
                />
              )}
              {chart.kind !== "line" &&
                s.x.map((x, i) =>
                  s.y[i] === null ? null : chart.kind === "scatter" ? (
                    <circle
                      key={i}
                      cx={X(x)}
                      cy={Y(s.y[i]!)}
                      r="3.5"
                      fill={colors[j]}
                    />
                  ) : (
                    <rect
                      key={i}
                      x={X(x) - barGroupWidth / 2 + j * barWidth}
                      y={Math.min(Y(0), Y(s.y[i]!))}
                      width={barWidth}
                      height={Math.abs(Y(s.y[i]!) - Y(0))}
                      fill={colors[j]}
                    />
                  ),
                )}
            </g>
          );
        })}
        {current.y !== null && (
          <g>
            <line
              x1={X(current.x)}
              x2={X(current.x)}
              y1={top}
              y2={bottom}
              stroke="#9aa7bd"
              strokeDasharray="3 4"
            />
            <circle
              cx={X(current.x)}
              cy={Y(current.y)}
              r="5"
              fill={current.color}
              stroke="white"
              strokeWidth="2"
            />
          </g>
        )}
      </svg>
      <label className="chart-control">
        استكشف النقاط بلوحة المفاتيح
        <input
          aria-label="النقطة المعروضة"
          type="range"
          min="0"
          max={points.length - 1}
          value={selected}
          onChange={(e) => setSelected(Number(e.target.value))}
        />
      </label>
      <output className="chart-readout" aria-live="polite">
        <span>{current.label}</span>{" "}
        <bdi>
          x = {format(current.x)} · y ={" "}
          {current.y === null ? "undefined" : format(current.y)}
        </bdi>
      </output>
      <p className="science-caveat">
        فحص شكل البيانات وحدودها لا يثبت صحة النموذج الفيزيائي. المنحنى العيّني
        لا يثبت الاستمرارية أو القيم القصوى.
      </p>
      <details>
        <summary>اعرض القيم وبيانات المصدر الحسابي</summary>
        <p className="muted">
          <bdi>{result.output.expression || result.output.origin}</bdi>
        </p>
        <div className="table-scroll chart-data">
          <table>
            <thead>
              <tr>
                <th>السلسلة</th>
                <th dir="ltr">x</th>
                <th dir="ltr">y</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p, i) => (
                <tr key={i}>
                  <td>{p.label}</td>
                  <td dir="ltr">{String(p.x)}</td>
                  <td dir="ltr">{p.y === null ? "undefined" : String(p.y)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </figure>
  );
}

type Diagram = {
  title: string;
  x_label: string;
  y_label: string;
  x_min: number;
  x_max: number;
  y_min: number;
  y_max: number;
  elements: {
    kind: string;
    x: number;
    y: number;
    x2?: number;
    y2?: number;
    radius?: number;
    label: string;
  }[];
};
export function ScientificDiagram({ result }: { result: ScientificResult }) {
  const d = result.output.diagram as Diagram;
  const id = useId().replace(/:/g, ""),
    ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const observer = new ResizeObserver((entries) =>
      setWidth(Math.max(280, Math.min(900, entries[0].contentRect.width))),
    );
    if (ref.current) observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  if (!d || !d.elements.length) return <p>مخطط غير صالح.</p>;
  const height = width < 500 ? 280 : 370,
    margin = 36;
  const scale = Math.min(
    (width - 2 * margin) / (d.x_max - d.x_min),
    (height - 2 * margin) / (d.y_max - d.y_min),
  );
  const X = (x: number) => width / 2 + (x - (d.x_min + d.x_max) / 2) * scale,
    Y = (y: number) => height / 2 - (y - (d.y_min + d.y_max) / 2) * scale;
  return (
    <figure
      className="scientific-chart scientific-diagram"
      ref={ref}
      aria-label="مخطط علمي هندسي"
    >
      <figcaption>
        <strong>{d.title}</strong>
        <span className="muted">مخطط من إحداثيات مقدّمة — ليس صورة مصدر</span>
      </figcaption>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={d.title}
        style={{ direction: "ltr" }}
      >
        <defs>
          <marker
            id={id}
            markerWidth="8"
            markerHeight="8"
            refX="7"
            refY="4"
            orient="auto"
            markerUnits="strokeWidth"
          >
            <path d="M0 0 L8 4 L0 8 Z" fill="#215db0" />
          </marker>
        </defs>
        {d.x_min <= 0 && d.x_max >= 0 && (
          <line
            x1={X(0)}
            x2={X(0)}
            y1={Y(d.y_min)}
            y2={Y(d.y_max)}
            stroke="#b3bdcf"
            strokeDasharray="3 4"
          />
        )}
        {d.y_min <= 0 && d.y_max >= 0 && (
          <line
            x1={X(d.x_min)}
            x2={X(d.x_max)}
            y1={Y(0)}
            y2={Y(0)}
            stroke="#b3bdcf"
            strokeDasharray="3 4"
          />
        )}
        {d.elements.map((e, i) => (
          <g key={i}>
            {e.kind === "circle" ? (
              <circle
                cx={X(e.x)}
                cy={Y(e.y)}
                r={e.radius! * scale}
                fill="#e4edf9"
                stroke="#215db0"
                strokeWidth="2"
              />
            ) : e.kind === "point" ? (
              <circle cx={X(e.x)} cy={Y(e.y)} r="4" fill="#215db0" />
            ) : (
              <line
                x1={X(e.x)}
                y1={Y(e.y)}
                x2={X(e.x2!)}
                y2={Y(e.y2!)}
                stroke="#215db0"
                strokeWidth="2.5"
                markerEnd={e.kind === "vector" ? `url(#${id})` : undefined}
              />
            )}
            <text
              x={X(e.x2 ?? e.x) + 8}
              y={Y(e.y2 ?? e.y) - 9}
              textAnchor="start"
            >
              {e.label}
            </text>
          </g>
        ))}
        <text x={width / 2} y={height - 5} textAnchor="middle">
          {d.x_label} · {d.y_label} — equal axis scale
        </text>
      </svg>
      <p className="science-caveat">
        تساوي مقياس المحورين يحافظ على هندسة الرسم؛ فحص الإحداثيات ليس تحققًا من
        صحة القوى أو النموذج الفيزيائي.
      </p>
      <details>
        <summary>إحداثيات المخطط وحدود الفحص</summary>
        <pre tabIndex={0} dir="ltr">
          {JSON.stringify(
            { inputs: result.inputs, scope: result.output.scope },
            null,
            2,
          )}
        </pre>
      </details>
    </figure>
  );
}
