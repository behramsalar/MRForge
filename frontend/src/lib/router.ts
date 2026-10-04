import { useEffect, useState } from "react";

/**
 * A tiny hash router. Addresses: "#/" (workspaces), "#/settings", "#/design", and
 * "#/w/<workspace>/<page>/<extra>" where the extra part means different things per page
 * (an import for data, a tab for process, a subject for viewer). Reload-safe, no server rules.
 */
export type Route = { workspace?: string; page: string; extra?: string };

/** Addresses used before the sidebar existed keep working. */
const LEGACY: Record<string, { page: string; extra?: string; keepExtra?: boolean }> = {
  import: { page: "data", keepExtra: true },
  anat: { page: "process", extra: "anat" },
  func: { page: "process", extra: "func" },
  view: { page: "viewer", keepExtra: true },
};

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "design") return { page: "design" };
  if (parts[0] === "settings") return { page: "settings" };
  if (parts[0] === "w" && parts[1]) {
    const raw = parts[2] ?? "dashboard";
    const legacy = LEGACY[raw];
    if (legacy) {
      return { workspace: parts[1], page: legacy.page, extra: legacy.keepExtra ? parts[3] : legacy.extra };
    }
    return { workspace: parts[1], page: raw, extra: parts[3] };
  }
  return { page: "workspaces" };
}

export function href(workspace: string, page: string, extra?: string): string {
  return `#/w/${encodeURIComponent(workspace)}/${page}${extra ? `/${encodeURIComponent(extra)}` : ""}`;
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(location.hash));
  useEffect(() => {
    const on = () => setRoute(parse(location.hash));
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return route;
}
