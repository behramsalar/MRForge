import { href } from "./router";

/** One thing the command palette (Cmd/Ctrl+K) can jump to or do. */
export type Entry = {
  id: string;
  group: "Pages" | "Subjects" | "Actions";
  label: string;
  hint?: string; // shown small after the label
  to?: string; // an address to open
  action?: "theme" | "researcher" | "shortcuts" | "workspaces"; // or something to do
};

type NavLike = { id: string; label: string; children?: { id: string; label: string }[] }[];

/** Everything reachable inside an open workspace: pages, subjects, a few actions. */
export function buildEntries(ws: string | undefined, nav: NavLike, subjects: string[]): Entry[] {
  const out: Entry[] = [];
  if (ws) {
    for (const n of nav) {
      out.push({ id: `page:${n.id}`, group: "Pages", label: n.label, to: href(ws, n.id, n.children?.[0]?.id) });
      for (const c of n.children ?? []) {
        out.push({
          id: `page:${n.id}/${c.id}`,
          group: "Pages",
          label: c.label,
          hint: n.label,
          to: href(ws, n.id, c.id),
        });
      }
    }
    for (const s of subjects) out.push({ id: `subject:${s}`, group: "Subjects", label: s, to: href(ws, "subject", s) });
  }
  out.push(
    { id: "page:system", group: "Pages", label: "System", to: "#/system" },
    { id: "page:settings", group: "Pages", label: "Settings", to: "#/settings" },
    { id: "act:workspaces", group: "Actions", label: "All workspaces", action: "workspaces" },
    { id: "act:theme", group: "Actions", label: "Switch light / dark", action: "theme" },
    { id: "act:researcher", group: "Actions", label: "Switch researcher", action: "researcher" },
    { id: "act:shortcuts", group: "Actions", label: "Show keyboard shortcuts", hint: "?", action: "shortcuts" },
  );
  return out;
}

/** Every word typed must appear in the label or hint (any order, any case); label hits first. */
export function filterEntries(entries: Entry[], query: string, limit = 30): Entry[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return entries.slice(0, limit);
  const scored: [number, Entry][] = [];
  for (const e of entries) {
    const label = e.label.toLowerCase();
    const all = `${label} ${(e.hint ?? "").toLowerCase()}`;
    if (!words.every((w) => all.includes(w))) continue;
    const starts = words.every((w) => label.split(/[\s-]+/).some((p) => p.startsWith(w)));
    scored.push([starts ? 0 : words.every((w) => label.includes(w)) ? 1 : 2, e]);
  }
  return scored.sort((a, b) => a[0] - b[0]).map(([, e]) => e).slice(0, limit);
}
