import { Tabs } from "@radix-ui/themes";
import type { WorkspaceState } from "../api/types";
import { PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space } from "../theme/tokens";
import { AnatomicalPage } from "./AnatomicalPage";
import { FunctionalPage } from "./FunctionalPage";

/** Processing, step by step (full processing arrives in the next step). */
export function ProcessPage({ ws, tab, state }: { ws: string; tab?: string; state: WorkspaceState | null }) {
  const current = tab === "func" ? "func" : "anat";
  return (
    <>
      <PageHeader title="Process" description="Run the processing steps for a subject." />
      <Tabs.Root value={current} onValueChange={(v) => (location.hash = href(ws, "process", v))}>
        <Tabs.List>
          <Tabs.Trigger value="anat">Anatomical</Tabs.Trigger>
          <Tabs.Trigger value="func">Functional</Tabs.Trigger>
        </Tabs.List>
        <div style={{ paddingTop: `var(--space-${space.section})` }}>
          {current === "func" ? <FunctionalPage ws={ws} state={state} /> : <AnatomicalPage ws={ws} state={state} />}
        </div>
      </Tabs.Root>
    </>
  );
}
