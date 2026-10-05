import { createContext, useContext, type ReactNode } from "react";
import { useWorkspaceState } from "../api/hooks";
import type { WorkspaceState } from "../api/types";

type Ctx = { ws: string; state: WorkspaceState | null; connected: boolean };
const WorkspaceContext = createContext<Ctx | null>(null);

/** The open workspace and its live state (jobs, operations, imports), for every page. */
export function WorkspaceProvider({ ws, children }: { ws: string; children: ReactNode }) {
  const { state, connected } = useWorkspaceState(ws);
  return <WorkspaceContext.Provider value={{ ws, state, connected }}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): Ctx {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace needs an open workspace");
  return ctx;
}
