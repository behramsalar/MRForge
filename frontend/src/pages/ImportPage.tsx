import type { WorkspaceState } from "../api/types";
import { PageHeader } from "../components/ui/Layout";
import { space } from "../theme/tokens";
import { ImportsTab } from "./data/ImportsTab";

/** Import: bring scans into the workspace and follow what each import did. The address extra is the id of an import. */
export function ImportPage({ ws, extra, state }: { ws: string; extra?: string; state: WorkspaceState | null }) {
  return (
    <>
      <PageHeader title="Import" description="Bring scans into this workspace: DICOM folders, NIfTI files or a BIDS dataset." />
      <div style={{ paddingTop: `var(--space-${space.section})` }}>
        <ImportsTab ws={ws} importId={extra} state={state} />
      </div>
    </>
  );
}
