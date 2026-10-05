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
export function identityTracks(catalogue: StudyCatalogue, value: any) {
  return [
    ...new Set<string>(
      (value.tracks ?? (value.track ? [value.track] : []))
        .map((t: string) => canonical(catalogue.tracks, t))
        .filter(Boolean),
    ),
  ];
}
export function sourceIdentity(catalogue: StudyCatalogue, value: any) {
  const tracks = identityTracks(catalogue, value);
  const subjects =
    catalogue.tracks.find((x) => x.id === tracks[0])?.subjects || [];
  return {
    ...value,
    tracks,
    track: tracks[0] || "",
    subject: canonical(subjects, value.subject),
  };
}
export function IdentityChoices({
  catalogue,
  value,
  onChange,
  disabled = false,
  labels = ["الشعب المستهدفة", "المادة"],
}: {
  catalogue: StudyCatalogue;
  value: any;
  onChange: (v: any) => void;
  disabled?: boolean;
  labels?: string[];
}) {
  const selected = identityTracks(catalogue, value);
  const subjects = (
    catalogue.tracks.find((x) => x.id === selected[0])?.subjects || []
  ).filter((q) =>
    selected.every((t) =>
      catalogue.tracks
        .find((x) => x.id === t)
        ?.subjects.some((s) => s.id === q.id),
    ),
  );
  function toggle(id: string, checked: boolean) {
    const tracks = checked
      ? [...selected, id]
      : selected.filter((t) => t !== id);
    const current = canonical(
      catalogue.tracks.flatMap((x) => x.subjects),
      value.subject,
    );
    const supported =
      tracks.length &&
      tracks.every((t) =>
        catalogue.tracks
          .find((x) => x.id === t)
          ?.subjects.some((q) => q.id === current),
      );
    onChange({
      ...value,
      tracks,
      track: tracks[0] || "",
      subject: supported ? current : "",
    });
  }
  return (
    <>
      <fieldset className="source-tracks" disabled={disabled}>
        <legend>{labels[0]}</legend>
        <p className="muted">
          يمكن اختيار أكثر من شعبة للملف نفسه؛ لن يُكرر الكتاب أو استخراجه.
        </p>
        <div className="source-track-options">
          {catalogue.tracks.map((t, i) => (
            <label key={t.id}>
              <input
                aria-label={labels[0] + ": " + t.label}
                type="checkbox"
                required={i === 0 && !selected.length}
                checked={selected.includes(t.id)}
                onChange={(e) => toggle(t.id, e.target.checked)}
              />
              {t.label}
            </label>
          ))}
        </div>
      </fieldset>
      <label>
        {labels[1]}
        <select
          aria-label={labels[1]}
          required
          disabled={disabled || !selected.length}
          value={canonical(subjects, value.subject)}
          onChange={(e) =>
            onChange({
              ...value,
              tracks: selected,
              track: selected[0] || "",
              subject: e.target.value,
            })
          }
        >
          <option value="">اختر المادة</option>
          {subjects.map((x) => (
            <option key={x.id} value={x.id}>
              {x.label}
            </option>
          ))}
        </select>
        <span className="muted">
          تظهر المواد المتاحة لجميع الشعب المختارة فقط.
        </span>
      </label>
    </>
  );
}
