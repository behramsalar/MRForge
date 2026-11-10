import type { WorkspaceState } from "../api/types";
import { ImportsTab } from "./data/ImportsTab";

/** Import: bring scans into the workspace and follow what each import did. The address extra is the id of an import. */
export function ImportPage({ ws, extra, state }: { ws: string; extra?: string; state: WorkspaceState | null }) {
  return <ImportsTab ws={ws} importId={extra} state={state} />;
}
