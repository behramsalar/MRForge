import type { WorkspaceState } from "../api/types";
import { FullProcessingPage } from "./FullProcessingPage";

/** Processing is one page: every stage (preprocessing, analysis, diffusion) is a tile on it, and
 * running a single stage means leaving the others off. */
export function ProcessPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  return <FullProcessingPage ws={ws} state={state} />;
}
