import { Button, Card, Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import { useOverview } from "../api/hooks";
import type { WorkspaceState } from "../api/types";
import { ConfirmProcessDialog } from "../components/ConfirmProcessDialog";
import { StageChips } from "../components/StageChips";
import { SubjectsTable } from "../components/SubjectsTable";
import { EmptyState, PageHeader } from "../components/ui/Layout";
import { href } from "../lib/router";
import { space, type } from "../theme/tokens";

/** One processing stage on its own, for a subject whose earlier stages are done. The stage list
 * and the settings come from the plan, so this page only chooses the subject and the stage. */
export function StagePage({
  ws,
  state,
  stage,
  title,
  description,
}: {
  ws: string;
  state: WorkspaceState | null;
  stage: string;
  title: string;
  description: string;
}) {
  const overview = useOverview(ws);
  const [chosen, setChosen] = useState<string | undefined>();
  const [confirm, setConfirm] = useState(false);
  const rows = (overview.data?.subjects ?? []).filter((s) => s.n_files > 0);
  const row = rows.find((s) => s.label === chosen);
  const busy = !!state?.operations.some((o) => o.status === "Queued" || o.status === "Running");
  return (
    <Flex direction="column" gap={space.section}>
      <PageHeader title={title} description={description} />
      {overview.data && rows.length === 0 && (
        <EmptyState title="There is no data to process yet" text="Import your scans first." action="Import scans" href={href(ws, "data")} />
      )}
      {rows.length > 0 && (
        <>
          <Text size={type.help} color="gray">
            Choose a subject. The earlier stages must be done already; their results are used as they are.
          </Text>
          <SubjectsTable subjects={rows} selected={chosen ? [chosen] : []} onSelect={(l) => setChosen(l[0])} />
        </>
      )}
      {row && (
        <Card size="3">
          <Flex gap={space.group} align="center" wrap="wrap" justify="between">
            <Flex direction="column" gap="1">
              <Text weight="bold">{row.label}</Text>
              <StageChips stages={row.stages} />
            </Flex>
            <Button size="3" disabled={busy} onClick={() => setConfirm(true)}>
              Run {title.toLowerCase()} for {row.label}…
            </Button>
          </Flex>
        </Card>
      )}
      {row && <ConfirmProcessDialog ws={ws} subject={row.label} open={confirm} onOpenChange={setConfirm} onlyStage={stage} />}
    </Flex>
  );
}
