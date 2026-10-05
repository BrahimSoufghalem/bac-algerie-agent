import React from "react";
export type StudyCatalogue = {
  tracks: {
    id: string;
    label: string;
    aliases?: string[];
    subjects: { id: string; label: string; aliases?: string[] }[];
  }[];
  content_types: { id: string; label: string; kind: string }[];
};
export const emptyCatalogue: StudyCatalogue = { tracks: [], content_types: [] };
export function canonical(
  items: { id: string; label: string; aliases?: string[] }[],
  value: string,
) {
  const text = (value || "").trim().toLocaleLowerCase();
  return (
    items.find((x) =>
      [x.id, x.label, ...(x.aliases || [])].some(
        (a) => a.toLocaleLowerCase() === text,
      ),
    )?.id || ""
  );
}
export function IdentityChoices({
  catalogue,
  value,
  onChange,
  disabled = false,
  labels = ["الشعبة", "المادة"],
}: {
  catalogue: StudyCatalogue;
  value: any;
  onChange: (v: any) => void;
  disabled?: boolean;
  labels?: string[];
}) {
  const track = canonical(catalogue.tracks, value.track);
  const subjects = catalogue.tracks.find((x) => x.id === track)?.subjects || [];
  return (
    <>
      <label>
        {labels[0]}
        <select
          required
          aria-label={labels[0]}
          disabled={disabled}
          value={track}
          onChange={(e) =>
            onChange({ ...value, track: e.target.value, subject: "" })
          }
        >
          <option value="">اختر الشعبة</option>
          {catalogue.tracks.map((x) => (
            <option key={x.id} value={x.id}>
              {x.label}
            </option>
          ))}
        </select>
      </label>
      <label>
        {labels[1]}
        <select
          required
          aria-label={labels[1]}
          disabled={disabled || !track}
          value={canonical(subjects, value.subject)}
          onChange={(e) =>
            onChange({ ...value, track, subject: e.target.value })
          }
        >
          <option value="">اختر المادة</option>
          {subjects.map((x) => (
            <option key={x.id} value={x.id}>
              {x.label}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}
