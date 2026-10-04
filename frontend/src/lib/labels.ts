/** Plain-language names for the technical terms the engine uses. */
export const kindLabel: Record<string, string> = {
  T1w: "T1-weighted anatomical",
  T2w: "T2-weighted anatomical",
  FLAIR: "FLAIR anatomical",
  bold: "Functional (BOLD)",
  dwi: "Diffusion",
  "fieldmap-magnitude": "Fieldmap, magnitude image",
  "fieldmap-phase": "Fieldmap, phase image",
  localizer: "Scanner localizer",
  "scanner-report": "Scanner report",
  "scanner-generated": "Made by the scanner (copy or map)",
  "skipped-by-user": "Skipped by you",
};

export function kindName(kind: string): string {
  return kindLabel[kind] ?? kind;
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
  return d.toLocaleString();
}

export function elapsed(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return "";
  const norm = (v: string) => new Date(v.endsWith("Z") || v.includes("+") ? v : v + "Z").getTime();
  const secs = Math.max(0, Math.round(((end ? norm(end) : Date.now()) - norm(start)) / 1000));
  if (secs < 60) return `${secs} s`;
  const m = Math.floor(secs / 60);
  return m < 60 ? `${m} min ${secs % 60} s` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export const datatypeLabel: Record<string, string> = {
  anat: "Anatomical",
  func: "Functional",
  fmap: "Fieldmap",
  dwi: "Diffusion",
};

export function humanSize(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(1)} GB`;
  if (bytes >= 1e6) return `${Math.round(bytes / 1e6)} MB`;
  return `${Math.max(1, Math.round(bytes / 1e3))} kB`;
}

/** "74 x 74 x 62, 360 volumes" from an image shape. */
export function describeShape(shape: number[] | null | undefined): string {
  if (!shape || shape.length < 3) return "-";
  const grid = shape.slice(0, 3).join(" x ");
  return shape.length > 3 && shape[3] > 1 ? `${grid}, ${shape[3]} volumes` : grid;
}

/** Seconds without float noise: 0.6500000965 -> "0.65 s". */
export function seconds(value: number | null | undefined): string {
  return value ? `${Number(value.toFixed(3))} s` : "-";
}
