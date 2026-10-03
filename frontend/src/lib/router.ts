import { useEffect, useState } from "react";

/** A tiny hash router: "#/w/<workspace>/<page>/<extra>". Reload-safe and needs no server rules. */
export type Route = { workspace?: string; page: string; extra?: string };

export function parse(hash: string): Route {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "design") return { page: "design" };
  if (parts[0] === "w" && parts[1]) {
    return { workspace: parts[1], page: parts[2] ?? "import", extra: parts[3] };
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
