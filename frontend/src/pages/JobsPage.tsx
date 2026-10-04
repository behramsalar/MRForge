import type { WorkspaceState } from "../api/types";
import { JobsPanel } from "../components/JobsPanel";
import { EmptyState, PageHeader } from "../components/ui/Layout";

/** Everything that ran in this workspace (the history view grows in a later step). */
export function JobsPage({ ws, state }: { ws: string; state: WorkspaceState | null }) {
  const jobs = state?.jobs ?? [];
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  return (
    <>
      <PageHeader title="Jobs" description="Every processing step that ran in this workspace." />
      {state && jobs.length === 0 ? (
        <EmptyState title="Nothing has run yet" text="Steps you start from the Process page show up here, with their logs." />
      ) : (
        <JobsPanel ws={ws} jobs={jobs} busy={busy} />
      )}
    </>
  );
}
