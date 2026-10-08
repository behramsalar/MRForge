/**
 * The arrangement of the pictures in a report: order, size and hidden. Pure functions, so the
 * rules (the same ones the saved HTML file applies) are tested without a screen.
 *
 * `items` is the saved list; a picture that is not in it keeps its original place and the
 * default size. Order only matters inside one group of pictures (the slices of one QC picture).
 */
export type Size = "s" | "m" | "l";
export type LayoutItem = { image: string; hidden?: boolean; size?: Size };
export type Arranged = { image: string; hidden: boolean; size: Size };

export const SIZES: Size[] = ["s", "m", "l"];

/** The pictures of one group in the order to show them, with every setting filled in. */
export function arrange(paths: string[], items: LayoutItem[], defaultSize: Size): Arranged[] {
  const place = new Map(items.map((i, n) => [i.image, n]));
  const by = new Map(items.map((i) => [i.image, i]));
  return [...paths]
    .map((image, n) => ({ image, n }))
    .sort((a, b) => (place.get(a.image) ?? items.length + a.n) - (place.get(b.image) ?? items.length + b.n))
    .map(({ image }) => ({
      image,
      hidden: by.get(image)?.hidden ?? false,
      size: by.get(image)?.size ?? defaultSize,
    }));
}

/** The list with every picture of this group written out, in its current order. */
export function materialise(paths: string[], items: LayoutItem[], defaultSize: Size): LayoutItem[] {
  const mine = new Set(paths);
  return [...items.filter((i) => !mine.has(i.image)), ...arrange(paths, items, defaultSize)];
}

function change(items: LayoutItem[], image: string, patch: Partial<LayoutItem>): LayoutItem[] {
  return items.map((i) => (i.image === image ? { ...i, ...patch } : i));
}

export function move(items: LayoutItem[], paths: string[], image: string, delta: -1 | 1, defaultSize: Size): LayoutItem[] {
  const all = materialise(paths, items, defaultSize);
  const group = all.filter((i) => paths.includes(i.image));
  const rest = all.filter((i) => !paths.includes(i.image));
  const at = group.findIndex((i) => i.image === image);
  const to = at + delta;
  if (at < 0 || to < 0 || to >= group.length) return all;
  [group[at], group[to]] = [group[to], group[at]];
  return [...rest, ...group];
}

export function resize(items: LayoutItem[], paths: string[], image: string, size: Size, defaultSize: Size): LayoutItem[] {
  return change(materialise(paths, items, defaultSize), image, { size });
}

export function setHidden(items: LayoutItem[], paths: string[], image: string, hidden: boolean, defaultSize: Size): LayoutItem[] {
  return change(materialise(paths, items, defaultSize), image, { hidden });
}

/** Next size when the size button is pressed: small, medium, large, small... */
export function nextSize(size: Size): Size {
  return SIZES[(SIZES.indexOf(size) + 1) % SIZES.length];
}
