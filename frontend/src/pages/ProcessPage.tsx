import type { WorkspaceState } from "../api/types";
import { defaultChild } from "../shell/nav";
import { AnatomicalPage } from "./AnatomicalPage";
import { FunctionalPage } from "./FunctionalPage";

/** The kinds of processing; the sidebar tree chooses which one is shown. */
export function ProcessPage({ ws, tab, state }: { ws: string; tab?: string; state: WorkspaceState | null }) {
  const current = tab ?? defaultChild("process");
  return current === "func" ? <FunctionalPage ws={ws} state={state} /> : <AnatomicalPage ws={ws} state={state} />;
}
