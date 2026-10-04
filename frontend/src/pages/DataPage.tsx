import { Tabs } from "@radix-ui/themes";
import type { WorkspaceState } from "../api/types";
import { PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space } from "../theme/tokens";
import { ImportsTab } from "./data/ImportsTab";
import { SubjectsTab } from "./data/SubjectsTab";

/** Data: bring scans in and see what each subject has. The address extra is either
 * "subjects" or the id of an import ("import-002"). */
export function DataPage({ ws, extra, state }: { ws: string; extra?: string; state: WorkspaceState | null }) {
  const tab = extra === "subjects" ? "subjects" : "imports";
  return (
    <>
      <PageHeader title="Data" description="Bring scans into this workspace and see what each subject has." />
      <Tabs.Root value={tab} onValueChange={(v) => (location.hash = href(ws, "data", v === "subjects" ? "subjects" : undefined))}>
        <Tabs.List>
          <Tabs.Trigger value="imports">Imports</Tabs.Trigger>
          <Tabs.Trigger value="subjects">Subjects and files</Tabs.Trigger>
        </Tabs.List>
        <div style={{ paddingTop: `var(--space-${space.section})` }}>
          {tab === "subjects" ? <SubjectsTab ws={ws} /> : <ImportsTab ws={ws} importId={extra} state={state} />}
        </div>
      </Tabs.Root>
    </>
  );
}
