import { useEffect, useState } from "react";

/**
 * A tiny hash router. Addresses: "#/" (workspaces), "#/settings", "#/design", and
 * "#/w/<workspace>/<page>/<extra>" where the extra part means different things per page
 * (an import for data, a tab for process, a subject for viewer). Reload-safe, no server rules.
 */
export type Route = { workspace?: string; page: string; extra?: string; extra2?: string };

/** Addresses used before the sidebar existed keep working. */
const LEGACY: Record<string, { page: string; extra?: string; extra2?: string; keepExtra?: boolean }> = {
  import: { page: "data", keepExtra: true },
  anat: { page: "process" },
  func: { page: "process" },
  view: { page: "viewer", keepExtra: true },
};

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "design") return { page: "design" };
  if (parts[0] === "settings") return { page: "settings" };
  if (parts[0] === "system") return { page: "system" };
  if (parts[0] === "w" && parts[1]) {
    const raw = parts[2] ?? "dashboard";
    const legacy = LEGACY[raw];
    if (legacy) {
      return {
        workspace: parts[1],
        page: legacy.page,
        extra: legacy.keepExtra ? parts[3] : legacy.extra,
      };
    }
    if (raw === "process") {
      // Single-step pages were folded into the Process page; the results and review moved.
      const old = parts[3];
      if (old === "conn") return { workspace: parts[1], page: "results", extra: "connectivity" };
      if (old === "dwi") return { workspace: parts[1], page: "results", extra: "diffusion" };
      if (old === "ica") return { workspace: parts[1], page: "quality" };
      return { workspace: parts[1], page: "process" };
    }
    if (raw === "anatomical") return { workspace: parts[1], page: "process" };
    return { workspace: parts[1], page: raw, extra: parts[3], extra2: parts[4] };
  }
  return { page: "workspaces" };
}

export function href(workspace: string, page: string, extra?: string, extra2?: string): string {
  const tail = [extra, extra2].filter(Boolean).map((p) => `/${encodeURIComponent(p!)}`).join("");
  return `#/w/${encodeURIComponent(workspace)}/${page}${tail}`;
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
