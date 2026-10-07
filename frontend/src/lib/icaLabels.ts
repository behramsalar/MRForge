/** Component labels: the three choices and the bookkeeping the review screen needs. */
export type IcaLabel = "signal" | "noise" | "uncertain";

export const LABEL_NAMES: Record<IcaLabel, string> = {
  signal: "Signal",
  noise: "Noise",
  uncertain: "Uncertain",
};

// Same meaning everywhere: green = good, red = to remove, amber = you are not sure.
export const LABEL_COLOURS: Record<IcaLabel, "green" | "red" | "amber"> = {
  signal: "green",
  noise: "red",
  uncertain: "amber",
};

export type Labels = Record<number, IcaLabel>;

export function toLabels(saved: Record<string, string>): Labels {
  const out: Labels = {};
  for (const [k, v] of Object.entries(saved)) {
    if (v === "signal" || v === "noise" || v === "uncertain") out[Number(k)] = v;
  }
  return out;
}

export function counts(labels: Labels, total: number) {
  const n = { signal: 0, noise: 0, uncertain: 0, unlabelled: 0 };
  for (let i = 1; i <= total; i++) {
    const l = labels[i];
    if (l) n[l] += 1;
    else n.unlabelled += 1;
  }
  return n;
}

/** The first component after ``from`` (wrapping round) that has no label, or null. */
export function nextUnlabelled(labels: Labels, total: number, from: number): number | null {
  for (let step = 1; step <= total; step++) {
    const n = ((from - 1 + step) % total) + 1;
    if (!labels[n]) return n;
  }
  return null;
}

export function noiseList(labels: Labels): number[] {
  return Object.entries(labels)
    .filter(([, v]) => v === "noise")
    .map(([k]) => Number(k))
    .sort((a, b) => a - b);
}
