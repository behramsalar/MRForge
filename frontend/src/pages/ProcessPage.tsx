import type { WorkspaceState } from "../api/types";
import { AnatomicalPage } from "./AnatomicalPage";
import { FullProcessingPage } from "./FullProcessingPage";
import { FunctionalPage } from "./FunctionalPage";

/** The kind of processing chosen in the sidebar tree: Pipelines (the default), or one single step. */
export function ProcessPage({ ws, tab, state }: { ws: string; tab?: string; state: WorkspaceState | null }) {
  if (tab === "func") return <FunctionalPage ws={ws} state={state} />;
  if (tab === "anat") return <AnatomicalPage ws={ws} state={state} />;
  return <FullProcessingPage ws={ws} state={state} />;
}
