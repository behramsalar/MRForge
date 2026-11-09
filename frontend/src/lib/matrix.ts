import { matrixScale } from "../theme/tokens";

export type Stat = "r" | "z";
export type Rgb = readonly [number, number, number] | readonly number[];

/** Colour of one matrix value on the fixed, symmetric scale (null = missing). */
export function cellColor(value: number | null, stat: Stat, diagonal = false): [number, number, number] {
  if (diagonal) return [...matrixScale.diagonal] as [number, number, number];
  if (value === null || Number.isNaN(value)) return [...matrixScale.missing] as [number, number, number];
  const limit = matrixScale.range[stat];
  const t = Math.max(-1, Math.min(1, value / limit));
  const end = t < 0 ? matrixScale.negative : matrixScale.positive;
  const a = Math.abs(t);
  return [0, 1, 2].map((k) => Math.round(matrixScale.zero[k] + (end[k] - matrixScale.zero[k]) * a)) as [
    number,
    number,
    number,
  ];
}

/** Indices where a new group starts (hemisphere + network), or [] when there are too many to
 * draw calmly (an atlas that alternates left and right has a boundary at every cell). */
export function boundaries(groups: string[], maxGroups = 40): number[] {
  const starts: number[] = [];
  for (let i = 1; i < groups.length; i++) if (groups[i] !== groups[i - 1]) starts.push(i);
  return starts.length + 1 > maxGroups ? [] : starts;
}

/** Histogram of the values above the diagonal (each pair once), with fixed limits. */
export function histogram(matrix: (number | null)[][], stat: Stat, bins = 30): { counts: number[]; low: number; high: number } {
  const limit = matrixScale.range[stat];
  const counts = new Array<number>(bins).fill(0);
  for (let i = 0; i < matrix.length; i++) {
    for (let j = i + 1; j < matrix.length; j++) {
      const v = matrix[i][j];
      if (v === null || Number.isNaN(v)) continue;
      const k = Math.min(bins - 1, Math.max(0, Math.floor(((v + limit) / (2 * limit)) * bins)));
      counts[k] += 1;
    }
  }
  return { counts, low: -limit, high: limit };
}

/** Mean of the values above the diagonal, or null when there are none. */
export function meanOffDiagonal(matrix: (number | null)[][]): number | null {
  let sum = 0;
  let n = 0;
  for (let i = 0; i < matrix.length; i++)
    for (let j = i + 1; j < matrix.length; j++) {
      const v = matrix[i][j];
      if (v !== null && !Number.isNaN(v)) {
        sum += v;
        n += 1;
      }
    }
  return n ? sum / n : null;
}
